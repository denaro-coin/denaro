from datetime import datetime
from decimal import Decimal
from dateutil import parser
from typing import List, Union, Tuple

import asyncpg
from asyncpg import Connection, Pool, UndefinedTableError

from .helpers import sha256, point_to_string, string_to_point, point_to_bytes, AddressFormat
from .transactions import Transaction, CoinbaseTransaction, TransactionInput


class Database:
    connection: Connection = None
    credentials = {}
    instance = None
    pool: Pool = None

    @staticmethod
    async def create(user='denaro', password='', database='denaro', host='127.0.0.1', ignore: bool = False):
        self = Database()
        #self.connection = await asyncpg.connect(user=user, password=password, database=database, host=host)
        self.pool = await asyncpg.create_pool(
            user=user,
            password=password,
            database=database,
            host=host,
            command_timeout=30,
            min_size=3
        )
        if not ignore:
            async with self.pool.acquire() as connection:
                try:
                    res = await connection.fetchrow('SELECT * FROM unspent_outputs WHERE true LIMIT 1')
                    if res is None:
                        print('Unspent outputs missing, run create_unspent_outputs.py')
                        exit()
                except UndefinedTableError:
                    print('Unspent outputs missing, run create_unspent_outputs.py')
                    exit()
        Database.instance = self
        return self

    @staticmethod
    async def get():
        if Database.instance is None:
            await Database.create(**Database.credentials)
        return Database.instance

    """@property
    def connection(self):
        return await self.pool.acquire()"""

    async def add_pending_transaction(self, transaction: Transaction):
        if isinstance(transaction, CoinbaseTransaction):
            return False
        tx_hex = transaction.hex()
        if await self.get_transaction(sha256(tx_hex), False) is not None or not await transaction.verify():
            return False
        async with self.pool.acquire() as connection:
            await connection.fetch(
                'INSERT INTO pending_transactions (tx_hash, tx_hex, inputs_addresses, fees) VALUES ($1, $2, $3, $4)',
                sha256(tx_hex),
                tx_hex,
                [point_to_string(await tx_input.get_public_key()) for tx_input in transaction.inputs],
                transaction.fees
            )
        return True

    async def remove_pending_transaction(self, tx_hash: str):
        async with self.pool.acquire() as connection:
            await connection.fetch('DELETE FROM pending_transactions WHERE tx_hash = $1', tx_hash)

    async def remove_pending_transactions_by_hash(self, tx_hashes: List[str]):
        async with self.pool.acquire() as connection:
            await connection.fetch('DELETE FROM pending_transactions WHERE tx_hash = ANY($1)', tx_hashes)

    async def remove_pending_transactions(self):
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM pending_transactions')

    async def delete_blockchain(self):
        async with self.pool.acquire() as connection:
            await connection.execute('TRUNCATE transactions, blocks RESTART IDENTITY')

    async def delete_block(self, id: int):
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM blocks WHERE id = $1', id)

    async def delete_blocks(self, offset: int):
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM blocks WHERE id > $1', offset)

    async def get_pending_transactions_limit(self, limit: int = 1000, hex_only: bool = False) -> List[Union[Transaction, str]]:
        async with self.pool.acquire() as connection:
            txs = await connection.fetch(f'SELECT tx_hex FROM pending_transactions ORDER BY fees DESC LIMIT {limit}')
        txs_hex = sorted(tx['tx_hex'] for tx in txs)
        if hex_only:
            return txs_hex
        return [await Transaction.from_hex(tx_hex) for tx_hex in txs_hex]

    async def add_transaction(self, transaction: Union[Transaction, CoinbaseTransaction], block_hash: str):
        tx_hex = transaction.hex()
        async with self.pool.acquire() as connection:
            stmt = await connection.prepare('INSERT INTO transactions (block_hash, tx_hash, tx_hex, inputs_addresses, fees) VALUES ($1, $2, $3, $4, $5)')
            await stmt.fetchval(
                block_hash,
                sha256(tx_hex),
                tx_hex,
                [point_to_string(await tx_input.get_public_key()) for tx_input in transaction.inputs] if isinstance(transaction, Transaction) else [],
                transaction.fees if isinstance(transaction, Transaction) else 0
            )

    async def add_block(self, id: int, block_hash: str, address: str, random: int, difficulty: Decimal, reward: Decimal, timestamp: Union[datetime, str]):
        async with self.pool.acquire() as connection:
            stmt = await connection.prepare('INSERT INTO blocks (id, hash, address, random, difficulty, reward, timestamp) VALUES ($1, $2, $3, $4, $5, $6, $7)')
            await stmt.fetchval(
                id,
                block_hash,
                address,
                random,
                difficulty,
                reward,
                timestamp if isinstance(timestamp, datetime) else parser.parse(timestamp)
            )
        from .manager import Manager
        Manager.difficulty = None

    async def get_transaction(self, tx_hash: str, check_signatures: bool = True) -> Union[Transaction, CoinbaseTransaction]:
        async with self.pool.acquire() as connection:
            res = tx = await connection.fetchrow('SELECT tx_hex, block_hash FROM transactions WHERE tx_hash = $1', tx_hash)
        if res is not None:
            tx = await Transaction.from_hex(res['tx_hex'], check_signatures)
            tx.block_hash = res['block_hash']
        return tx

    async def get_pending_transaction(self, tx_hash: str, check_signatures: bool = True) -> Transaction:
        async with self.pool.acquire() as connection:
            res = await connection.fetchrow('SELECT tx_hex FROM pending_transactions WHERE tx_hash = $1', tx_hash)
        return await Transaction.from_hex(res['tx_hex'], check_signatures) if res is not None else None

    async def get_transactions(self, tx_hashes: List[str]):
        async with self.pool.acquire() as connection:
            res = await connection.fetch('SELECT tx_hex FROM transactions WHERE tx_hash = ANY($1)', tx_hashes)
        return {sha256(res['tx_hex']): await Transaction.from_hex(res['tx_hex']) for res in res}

    async def get_transaction_by_contains_multi(self, contains: List[str], ignore: str = None):
        async with self.pool.acquire() as connection:
            if ignore is not None:
                res = await connection.fetchrow(
                    'SELECT tx_hash FROM transactions WHERE tx_hex LIKE ANY($1) AND tx_hash != $2 LIMIT 1',
                    [f"%{contains}%" for contains in contains],
                    ignore
                )
            else:
                res = await connection.fetchrow(
                    'SELECT tx_hash FROM transactions WHERE tx_hex LIKE ANY($1) LIMIT 1',
                    [f"%{contains}%" for contains in contains],
                )
        return await Transaction.from_hex(res['tx_hex']) if res is not None else None

    async def get_pending_transactions_by_contains(self, contains: str):
        async with self.pool.acquire() as connection:
            res = await connection.fetch('SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE $1 AND tx_hash != $2', f"%{contains}%", contains)
        return [await Transaction.from_hex(res['tx_hex']) for res in res] if res is not None else None

    async def get_last_block(self) -> dict:
        async with self.pool.acquire() as connection:
            last_block = await connection.fetchrow("SELECT * FROM blocks ORDER BY id DESC LIMIT 1")
        if last_block is None:
            return None
        last_block = dict(last_block)
        last_block['address'] = last_block['address'].strip(' ')
        return last_block

    async def get_next_block_id(self) -> int:
        async with self.pool.acquire() as connection:
            last_id = await connection.fetchval('SELECT id FROM blocks ORDER BY id DESC LIMIT 1', column=0)
        last_id = last_id if last_id is not None else 0
        return last_id + 1

    async def get_block(self, block_hash: str) -> dict:
        async with self.pool.acquire() as connection:
            block = await connection.fetchrow('SELECT * FROM blocks WHERE hash = $1', block_hash)
            if block is None:
                return None
            block = dict(block)
            block['address'] = block['address'].strip(' ')
            return block

    async def get_blocks(self, offset: int, limit: int) -> list:
        async with self.pool.acquire() as connection:
            transactions: list = await connection.fetch(f'SELECT tx_hex, block_hash FROM transactions WHERE block_hash = ANY(SELECT hash FROM blocks WHERE id >= $1 ORDER BY id LIMIT $2)', offset, limit)
            blocks = await connection.fetch(f'SELECT * FROM blocks WHERE id >= $1 ORDER BY id LIMIT $2', offset, limit)
        result = []
        for block in blocks:
            block = dict(block)
            block['address'] = block['address'].strip(' ')
            block['timestamp'] = int(block['timestamp'].timestamp())
            txs = []
            for transaction in transactions.copy():
                if transaction['block_hash'] == block['hash']:
                    transactions.remove(transaction)
                    if isinstance(await Transaction.from_hex(transaction['tx_hex']), Transaction):
                        txs.append(transaction['tx_hex'])
            result.append({
                'block': block,
                'transactions': txs
            })
        return result

    async def get_block_by_id(self, block_id: int) -> dict:
        async with self.pool.acquire() as connection:
            block = await connection.fetchrow('SELECT * FROM blocks WHERE id = $1', block_id)
            if block is None:
                return None
            block = dict(block)
            block['address'] = block['address'].strip(' ')
            return block

    async def get_block_transactions(self, block_hash: str, check_signatures: bool = True) -> List[Union[Transaction, CoinbaseTransaction]]:
        async with self.pool.acquire() as connection:
            txs = await connection.fetch('SELECT * FROM transactions WHERE block_hash = $1', block_hash)
        return [await Transaction.from_hex(tx['tx_hex'], check_signatures) for tx in txs] if txs is not None else None

    async def add_unspent_outputs(self, outputs: List[Tuple[str, int]]) -> None:
        async with self.pool.acquire() as connection:
            await connection.executemany('INSERT INTO unspent_outputs (tx_hash, index) VALUES ($1, $2)', outputs)

    async def add_unspent_transactions_outputs(self, transactions: List[Transaction]) -> None:
        outputs = sum([[(transaction.hash(), index) for index in range(len(transaction.outputs))] for transaction in transactions], [])
        await self.add_unspent_outputs(outputs)

    async def remove_unspent_outputs(self, transactions: List[Transaction]) -> None:
        inputs = sum([[(tx_input.tx_hash, tx_input.index) for tx_input in transaction.inputs] for transaction in transactions], [])
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM unspent_outputs WHERE (tx_hash, index) = ANY($1::tx_output[])', inputs)

    async def get_unspent_outputs(self, outputs: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
        async with self.pool.acquire() as connection:
            results = await connection.fetch('SELECT tx_hash, index FROM unspent_outputs WHERE (tx_hash, index) = ANY($1::tx_output[])', outputs)
            return [(row['tx_hash'], row['index']) for row in results]

    async def get_unspent_outputs_from_all_transactions(self):
        async with self.pool.acquire() as connection:
            txs = await connection.fetch('SELECT tx_hex FROM transactions WHERE true')
            transactions = {sha256(tx['tx_hex']): await Transaction.from_hex(tx['tx_hex'], False) for tx in txs}
            outputs = sum([[transaction.hash() + bytes([index]).hex() for index in range(len(transaction.outputs))] for transaction in transactions.values()], [])
            for tx_hash, transaction in transactions.items():
                if isinstance(transaction, CoinbaseTransaction):
                    continue
                for output in outputs.copy():
                    if output in tx_hash:
                        outputs.remove(output)
            return [(output[:64], int(output[64:], 16)) for output in outputs]

    async def get_spendable_outputs(self, address: str, check_pending_txs: bool = False) -> List[TransactionInput]:
        point = string_to_point(address)
        search = ['%'+point_to_bytes(string_to_point(address), address_format).hex()+'%' for address_format in list(AddressFormat)]
        addresses = [point_to_string(point, address_format) for address_format in list(AddressFormat)]
        async with self.pool.acquire() as connection:
            txs = await connection.fetch('SELECT tx_hex FROM transactions WHERE tx_hex LIKE ANY($1)', search)
            spender_txs = await connection.fetch("SELECT tx_hex FROM transactions WHERE $1 && inputs_addresses", addresses)
            if check_pending_txs:
                spender_txs += await connection.fetch("SELECT tx_hex FROM pending_transactions WHERE $1 && inputs_addresses", addresses)
        inputs = []
        index = {}
        for tx in txs:
            used_outputs = []
            tx_hash = sha256(tx['tx_hex'])
            tx = await Transaction.from_hex(tx['tx_hex'], check_signatures=False)
            for i, tx_output in enumerate(tx.outputs):
                if tx_output.address in addresses and i not in used_outputs:
                    tx_input = TransactionInput(tx_hash, i)
                    tx_input.amount = tx_output.amount
                    tx_input.transaction = tx
                    index[tx_hash + str(i)] = tx_input
                    inputs.append(tx_input)
        used_outputs = []
        for spender_tx in spender_txs:
            spender_tx = await Transaction.from_hex(spender_tx['tx_hex'], check_signatures=False)
            for tx_input in spender_tx.inputs:
                if tx_input.tx_hash + str(tx_input.index) in index:
                    used_outputs.append(tx_input.tx_hash + str(tx_input.index))

        final = []
        for tx_input in inputs:
            if tx_input.tx_hash + str(tx_input.index) not in used_outputs:
                final.append(tx_input)

        return final

    async def get_address_balance(self, address: str, check_pending_txs: bool = False) -> Decimal:
        balance = Decimal(0)
        point = string_to_point(address)
        search = ['%'+point_to_bytes(string_to_point(address), address_format).hex()+'%' for address_format in list(AddressFormat)]
        addresses = [point_to_string(point, address_format) for address_format in list(AddressFormat)]
        for input in await self.get_spendable_outputs(address, check_pending_txs=check_pending_txs):
            balance += input.amount
        if check_pending_txs:
            async with self.pool.acquire() as connection:
                txs = await connection.fetch('SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE ANY($1)', search)
            for tx in txs:
                tx = await Transaction.from_hex(tx['tx_hex'], check_signatures=False)
                for i, tx_output in enumerate(tx.outputs):
                    if tx_output.address in addresses:
                        balance += tx_output.amount
        return balance
