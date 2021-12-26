import hashlib
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from math import ceil, floor, log
from typing import Tuple, List, Union

from icecream import ic

from . import Database
from .constants import MAX_SUPPLY, ENDIAN
from .helpers import sha256, timestamp, bytes_to_string, string_to_bytes
from .transactions import CoinbaseTransaction, Transaction

BLOCK_TIME = 180
BLOCKS_COUNT = 500
START_DIFFICULTY = Decimal('6.0')

_print = print
print = ic


def difficulty_to_hashrate_old(difficulty: Decimal) -> int:
    decimal = difficulty % 1 or 1/16
    return Decimal(16 ** int(difficulty) * (16 * decimal))


def difficulty_to_hashrate(difficulty: Decimal) -> int:
    decimal = difficulty % 1
    return Decimal(16 ** int(difficulty) * (16 / ceil(16 * (1 - decimal))))


def hashrate_to_difficulty_old(hashrate: int) -> Decimal:
    difficulty = int(log(hashrate, 16))
    if hashrate == 16 ** difficulty:
        return Decimal(difficulty)
    return Decimal(difficulty + (hashrate / Decimal(16) ** difficulty) / 16)


def hashrate_to_difficulty(hashrate: int) -> Decimal:
    difficulty = int(log(hashrate, 16))
    if hashrate == 16 ** difficulty:
        return Decimal(difficulty)
    ratio = hashrate / 16 ** difficulty

    decimal = 16 / ratio / 16
    decimal = 1 - floor(decimal * 10) / Decimal(10)
    return Decimal(difficulty + decimal)


async def calculate_difficulty() -> Tuple[Decimal, dict]:
    database = Database.instance
    async with database.pool.acquire() as connection:
        last_block = await connection.fetchrow("SELECT * FROM blocks ORDER BY id DESC LIMIT 1")
    if last_block is None:
        return START_DIFFICULTY, dict()
    last_block = dict(last_block)
    if last_block['id'] < BLOCKS_COUNT:
        return START_DIFFICULTY, last_block

    if last_block['id'] % BLOCKS_COUNT == 0:
        last_adjust_block = await database.get_block_by_id(last_block['id'] - BLOCKS_COUNT + 1)
        elapsed = last_block['timestamp'] - last_adjust_block['timestamp']
        elapsed = Decimal(elapsed.total_seconds())
        average_per_block = elapsed / BLOCKS_COUNT
        last_difficulty = last_block['difficulty']
        hashrate = difficulty_to_hashrate_old(last_difficulty) if last_block['id'] <= 17500 else difficulty_to_hashrate(last_difficulty)
        ratio = BLOCK_TIME / average_per_block
        hashrate *= ratio
        new_difficulty = hashrate_to_difficulty_old(hashrate) if last_block['id'] < 17500 else hashrate_to_difficulty(hashrate)
        new_difficulty = floor(new_difficulty * 10) / Decimal(10)
        return new_difficulty, last_block

    return last_block['difficulty'], last_block


async def get_difficulty() -> Tuple[Decimal, dict]:
    if Manager.difficulty is None:
        Manager.difficulty = await calculate_difficulty()
    return Manager.difficulty


async def check_block_is_valid(block_content: str, mining_info: tuple = None) -> bool:
    if mining_info is None:
        mining_info = await get_difficulty()
    difficulty, last_block = mining_info

    block_hash = sha256(block_content)

    if 'hash' not in last_block:
        return True

    last_block_hash = last_block['hash']

    decimal = difficulty % 1
    difficulty = floor(difficulty)
    if decimal > 0:
        charset = '0123456789abcdef'
        count = ceil(16 * (1 - decimal))
        return block_hash.startswith(last_block_hash[-difficulty:]) and block_hash[difficulty] in charset[:count]
    return block_hash.startswith(last_block_hash[-difficulty:])


def get_block_reward(number: int) -> Decimal:
    divider = floor(number / 150000)
    if divider == 0:
        return Decimal(100)
    if divider > 8:
        if number < 150000 * 9 + 458732 - 150000:
            return Decimal('0.390625')
        elif number < 150000 * 9 + 458733 - 150000:
            return Decimal('0.3125')
        return Decimal(0)
    return Decimal(100) / (2 ** Decimal(divider))


def __check():
    i = 0
    r = 0
    index = {}
    while n := get_block_reward(i):
        if n not in index:
            index[n] = 0
        index[n] += 1
        i += 1
        r += n

    print(r)
    print(MAX_SUPPLY - r)
    print(index)


async def clear_pending_transactions():
    database: Database = Database.instance
    transactions = await database.get_pending_transactions_limit(1000)

    used_inputs = []
    for transaction in transactions:
        tx_hash = sha256(transaction.hex())
        if not await transaction.verify() or await database.get_transaction(tx_hash, False) is not None:
            await database.remove_pending_transaction(tx_hash)
        else:
            tx_inputs = [f"{tx_input.tx_hash}{tx_input.index}" for tx_input in transaction.inputs]
            if any(used_input in tx_inputs for used_input in used_inputs):
                await database.remove_pending_transaction(tx_hash)
                return await clear_pending_transactions()
            used_inputs += tx_inputs


def get_transactions_merkle_tree_ordered(transactions: List[Union[Transaction, str]]):
    _bytes = bytes()
    for transaction in transactions:
        _bytes += hashlib.sha256(bytes.fromhex(transaction.hex() if isinstance(transaction, Transaction) else transaction)).digest()
    return hashlib.sha256(_bytes).hexdigest()


def get_transactions_merkle_tree(transactions: List[Union[Transaction, str]]):
    _bytes = bytes()
    transactions_bytes = []
    for transaction in transactions:
        transactions_bytes.append(bytes.fromhex(transaction.hex() if isinstance(transaction, Transaction) else transaction))
    for transaction in sorted(transactions_bytes):
        _bytes += hashlib.sha256(transaction).digest()
    return hashlib.sha256(_bytes).hexdigest()


def block_to_bytes(last_block_hash: str, block: dict) -> bytes:
    return bytes.fromhex(last_block_hash) + \
           string_to_bytes(block['address']) + \
           bytes.fromhex(block['merkle_tree']) + \
           block['timestamp'].to_bytes(4, byteorder=ENDIAN) + \
           int(block['difficulty'] * 10).to_bytes(2, ENDIAN) \
           + block['random'].to_bytes(4, ENDIAN)


def split_block_content(block_content: str):
    _bytes = bytes.fromhex(block_content)
    stream = BytesIO(_bytes)
    if len(_bytes) == 138:
        version = 1
    else:
        version = int.from_bytes(stream.read(1), ENDIAN)
        assert version > 1
        if version == 2:
            assert len(_bytes) == 108
        else:
            raise NotImplementedError()
    previous_hash = stream.read(32).hex()
    address = bytes_to_string(stream.read(64 if version == 1 else 33))
    merkle_tree = stream.read(32).hex()
    timestamp = int.from_bytes(stream.read(4), ENDIAN)
    difficulty = int.from_bytes(stream.read(2), ENDIAN) / Decimal(10)
    random = int.from_bytes(stream.read(4), ENDIAN)
    return previous_hash, address, merkle_tree, timestamp, difficulty, random


async def create_block(block_content: str, transactions: List[Transaction]):
    Manager.difficulty = None
    if not await check_block_is_valid(block_content):
        print('block not valid')
        return False

    difficulty, last_block = await get_difficulty()

    block_hash = sha256(block_content)
    previous_hash, address, merkle_tree, content_time, content_difficulty, random = split_block_content(block_content)
    content_time = int(content_time)
    if last_block != {} and (len(block_content) > 138 * 2 or previous_hash != last_block['hash']):
        return False

    if content_difficulty != difficulty:
        print('not same difficulty')
        print(content_difficulty)
        print(difficulty)
        return False

    if (last_block['timestamp'].timestamp() if 'timestamp' in last_block else 0) > content_time:
        print('timestamp younger than previous block')
        return False

    if content_time > timestamp():
        print('timestamp in the future')
        return False

    database: Database = Database.instance
    if len(transactions) > 1000:
        print('more than 1000 transactions')
        return False
    transactions = [tx for tx in transactions if isinstance(tx, Transaction)]

    fees = 0
    used_inputs = []
    for transaction in transactions:
        if not await transaction.verify():
            print('transaction has been not verified')
            return False
        else:
            tx_inputs = [f"{tx_input.tx_hash}{tx_input.index}" for tx_input in transaction.inputs]
            if any(used_input in tx_inputs for used_input in used_inputs):
                await database.remove_pending_transaction(sha256(transaction.hex()))
                return False
            else:
                used_inputs += tx_inputs
            fees += transaction.fees

    block_no = last_block['id'] + 1 if last_block != {} else 1

    transactions_merkle_tree = get_transactions_merkle_tree(transactions) if block_no >= 22500 else get_transactions_merkle_tree_ordered(transactions)
    if merkle_tree != transactions_merkle_tree:
        _print('merkle tree does not match')
        print(transactions)
        print(merkle_tree)
        print(get_transactions_merkle_tree(transactions))
        return False

    block_reward = get_block_reward(block_no)
    coinbase_transaction = CoinbaseTransaction(block_hash, address, block_reward + fees)

    try:
        await database.add_block(block_no, block_hash, address, random, difficulty, block_reward + fees, datetime.fromtimestamp(content_time))
    except Exception as e:
        print(e)
        raise
        return False

    if await coinbase_transaction.verify():
        await database.add_transaction(coinbase_transaction, block_hash)

    for transaction in transactions:
        try:
            await database.add_transaction(transaction, block_hash)
        except:
            await database.delete_block(block_no)
            return False
    await database.remove_pending_transactions_by_hash([sha256(transaction.hex()) for transaction in transactions])

    print(f'Added {len(transactions)} transactions in block (+ coinbase). Reward: {block_reward}, Fees: {fees}')
    Manager.difficulty = None
    return transactions


class Manager:
    difficulty: Tuple[float, dict] = None
