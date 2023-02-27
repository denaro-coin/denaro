import os
from datetime import datetime
from decimal import Decimal
from statistics import mean
from typing import List, Union, Tuple, Dict

import asyncpg
import pickledb
from asyncpg import Connection, Pool, UndefinedColumnError, UndefinedTableError

from .constants import MAX_BLOCK_SIZE_HEX, SMALLEST
from .helpers import sha256, point_to_string, string_to_point, point_to_bytes, AddressFormat, normalize_block
from .transactions import Transaction, CoinbaseTransaction, TransactionInput

dir_path = os.path.dirname(os.path.realpath(__file__))
OLD_BLOCKS_TRANSACTIONS_ORDER = pickledb.load(dir_path + '/old_block_transactions_order.json', True)


class Database:
    connection: Connection = None
    credentials = {}
    instance = None
    pool: Pool = None
    is_indexed = False

    @staticmethod
    async def create(user='denaro', password='', database='denaro', host='127.0.0.1', ignore: bool = False):
        self = Database()
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
                    await connection.fetchrow('SELECT outputs_addresses FROM transactions LIMIT 1')
                except UndefinedColumnError:
                    await connection.execute('ALTER TABLE transactions ADD COLUMN outputs_addresses TEXT[];'
                                              'ALTER TABLE transactions ADD COLUMN outputs_amounts BIGINT[];')
                try:
                    await connection.fetchrow('SELECT content FROM blocks LIMIT 1')
                except UndefinedColumnError:
                    await connection.execute('ALTER TABLE blocks ADD COLUMN content TEXT')
                try:
                    await connection.fetchrow('SELECT * FROM pending_spent_outputs LIMIT 1')
                except UndefinedTableError:
                    print('Creating pending_spent_outputs table')
                    await connection.execute("""CREATE TABLE IF NOT EXISTS pending_spent_outputs (
                        tx_hash CHAR(64) REFERENCES transactions(tx_hash) ON DELETE CASCADE,
                        index SMALLINT NOT NULL
                    )""")
                    print('Retrieving pending transactions')
                    txs = await connection.fetch('SELECT tx_hex FROM pending_transactions')
                    print('Adding pending transactions spent outputs')
                    await self.add_transactions_pending_spent_outputs([await Transaction.from_hex(tx['tx_hex'], False) for tx in txs])
                    print('Done.')
                res = await connection.fetchrow('SELECT outputs_addresses FROM transactions WHERE outputs_addresses IS NULL AND tx_hash = ANY(SELECT tx_hash FROM unspent_outputs);')
                self.is_indexed = res is None
                try:
                    await connection.fetchrow('SELECT address FROM unspent_outputs LIMIT 1')
                except UndefinedColumnError:
                    await connection.execute('ALTER TABLE unspent_outputs ADD COLUMN address TEXT NULL')
                    await self.set_unspent_outputs_addresses()


        Database.instance = self
        return self

    @staticmethod
    async def get():
        if Database.instance is None:
            await Database.create(**Database.credentials)
        return Database.instance

    async def add_pending_transaction(self, transaction: Transaction, verify: bool = True):
        if isinstance(transaction, CoinbaseTransaction):
            return False
        tx_hex = transaction.hex()
        if verify and not await transaction.verify_pending():
            return False
        async with self.pool.acquire() as connection:
            await connection.execute(
                'INSERT INTO pending_transactions (tx_hash, tx_hex, inputs_addresses, fees) VALUES ($1, $2, $3, $4)',
                sha256(tx_hex),
                tx_hex,
                [point_to_string(await tx_input.get_public_key()) for tx_input in transaction.inputs],
                transaction.fees
            )
        await self.add_transactions_pending_spent_outputs([transaction])
        return True

    async def remove_pending_transaction(self, tx_hash: str):
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM pending_transactions WHERE tx_hash = $1', tx_hash)

    async def remove_pending_transactions_by_hash(self, tx_hashes: List[str]):
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM pending_transactions WHERE tx_hash = ANY($1)', tx_hashes)

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

    async def get_pending_transactions_limit(self, limit: int = MAX_BLOCK_SIZE_HEX, hex_only: bool = False, check_signatures: bool = True) -> List[Union[Transaction, str]]:
        async with self.pool.acquire() as connection:
            txs = await connection.fetch(f'SELECT tx_hex FROM pending_transactions ORDER BY fees / LENGTH(tx_hex) DESC, LENGTH(tx_hex), tx_hex')
        txs_hex = [tx['tx_hex'] for tx in txs]
        return_txs = []
        size = 0
        for tx in txs_hex:
            if size + len(tx) > limit:
                break
            return_txs.append(tx)
            size += len(tx)
        if hex_only:
            return return_txs
        return [await Transaction.from_hex(tx_hex, check_signatures) for tx_hex in return_txs]

    async def get_next_block_average_fee(self):
        limit = MAX_BLOCK_SIZE_HEX
        async with self.pool.acquire() as connection:
            txs = await connection.fetch(f'SELECT LENGTH(tx_hex) as size, fees FROM pending_transactions ORDER BY fees / LENGTH(tx_hex) DESC, LENGTH(tx_hex) ASC')
        fees = []
        size = 0
        for tx in txs:
            if size + tx['size'] > limit:
                break
            fees.append(tx['fees'])
            size += tx['size']
        return int(mean(fees) * SMALLEST) // Decimal(SMALLEST)

    async def get_pending_blocks_count(self):
        async with self.pool.acquire() as connection:
            txs = await connection.fetch(f'SELECT LENGTH(tx_hex) as size FROM pending_transactions')
        return int(sum([tx['size'] for tx in txs]) / MAX_BLOCK_SIZE_HEX + 1)

    async def clear_duplicate_pending_transactions(self):
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM pending_transactions WHERE tx_hash = ANY(SELECT tx_hash FROM transactions)')

    async def add_transaction(self, transaction: Union[Transaction, CoinbaseTransaction], block_hash: str):
        await self.add_transactions([transaction], block_hash)

    async def add_transactions(self, transactions: List[Union[Transaction, CoinbaseTransaction]], block_hash: str):
        data = []
        for transaction in transactions:
            data.append((
                block_hash,
                transaction.hash(),
                transaction.hex(),
                [point_to_string(await tx_input.get_public_key()) for tx_input in transaction.inputs] if isinstance(transaction, Transaction) else [],
                [tx_output.address for tx_output in transaction.outputs],
                [tx_output.amount * SMALLEST for tx_output in transaction.outputs],
                transaction.fees if isinstance(transaction, Transaction) else 0
            ))
        async with self.pool.acquire() as connection:
            stmt = await connection.prepare('INSERT INTO transactions (block_hash, tx_hash, tx_hex, inputs_addresses, outputs_addresses, outputs_amounts, fees) VALUES ($1, $2, $3, $4, $5, $6, $7)')
            await stmt.executemany(data)

    async def add_block(self, id: int, block_hash: str, block_content: str, address: str, random: int, difficulty: Decimal, reward: Decimal, timestamp: Union[datetime, int]):
        async with self.pool.acquire() as connection:
            stmt = await connection.prepare('INSERT INTO blocks (id, hash, content, address, random, difficulty, reward, timestamp) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)')
            await stmt.fetchval(
                id,
                block_hash,
                block_content,
                address,
                random,
                difficulty,
                reward,
                timestamp if isinstance(timestamp, datetime) else datetime.utcfromtimestamp(timestamp)
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

    async def get_transaction_info(self, tx_hash: str) -> dict:
        async with self.pool.acquire() as connection:
            res = await connection.fetchrow('SELECT * FROM transactions WHERE tx_hash = $1', tx_hash)
        return dict(res) if res is not None else None

    async def get_transactions_info(self, tx_hashes: List[str]) -> Dict[str, dict]:
        async with self.pool.acquire() as connection:
            res = await connection.fetch('SELECT * FROM transactions WHERE tx_hash = ANY($1)', tx_hashes)
        return {res['tx_hash']: dict(res) for res in res}


    async def get_pending_transaction(self, tx_hash: str, check_signatures: bool = True) -> Transaction:
        async with self.pool.acquire() as connection:
            res = await connection.fetchrow('SELECT tx_hex FROM pending_transactions WHERE tx_hash = $1', tx_hash)
        return await Transaction.from_hex(res['tx_hex'], check_signatures) if res is not None else None

    async def get_pending_transactions_by_hash(self, hashes: List[str], check_signatures: bool = True) -> List[Transaction]:
        async with self.pool.acquire() as connection:
            res = await connection.fetch('SELECT tx_hex FROM pending_transactions WHERE tx_hash = ANY($1)', hashes)
        return [await Transaction.from_hex(tx['tx_hex'], check_signatures) for tx in res]

    async def get_transactions(self, tx_hashes: List[str]):
        async with self.pool.acquire() as connection:
            res = await connection.fetch('SELECT tx_hex FROM transactions WHERE tx_hash = ANY($1)', tx_hashes)
        return {sha256(res['tx_hex']): await Transaction.from_hex(res['tx_hex']) for res in res}

    async def get_transaction_hash_by_contains_multi(self, contains: List[str], ignore: str = None):
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
        return res['tx_hash'] if res is not None else None

    async def get_pending_transactions_by_contains(self, contains: str):
        async with self.pool.acquire() as connection:
            res = await connection.fetch('SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE $1 AND tx_hash != $2', f"%{contains}%", contains)
        return [await Transaction.from_hex(res['tx_hex']) for res in res] if res is not None else None

    async def remove_pending_transactions_by_contains(self, search: List[str]) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM pending_transactions WHERE tx_hex LIKE ANY($1)', [f"%{c}%" for c in search])

    async def get_pending_transaction_by_contains_multi(self, contains: List[str], ignore: str = None):
        async with self.pool.acquire() as connection:
            if ignore is not None:
                res = await connection.fetchrow(
                    'SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE ANY($1) AND tx_hash != $2 LIMIT 1',
                    [f"%{contains}%" for contains in contains],
                    ignore
                )
            else:
                res = await connection.fetchrow(
                    'SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE ANY($1) LIMIT 1',
                    [f"%{contains}%" for contains in contains],
                )
        return await Transaction.from_hex(res['tx_hex']) if res is not None else None

    async def get_last_block(self) -> dict:
        async with self.pool.acquire() as connection:
            last_block = await connection.fetchrow("SELECT * FROM blocks ORDER BY id DESC LIMIT 1")
        return normalize_block(last_block) if last_block is not None else None

    async def get_next_block_id(self) -> int:
        async with self.pool.acquire() as connection:
            last_id = await connection.fetchval('SELECT id FROM blocks ORDER BY id DESC LIMIT 1', column=0)
        last_id = last_id if last_id is not None else 0
        return last_id + 1

    async def get_block(self, block_hash: str) -> dict:
        async with self.pool.acquire() as connection:
            block = await connection.fetchrow('SELECT * FROM blocks WHERE hash = $1', block_hash)
        return normalize_block(block) if block is not None else None

    async def get_blocks(self, offset: int, limit: int) -> list:
        async with self.pool.acquire() as connection:
            transactions: list = await connection.fetch(f'SELECT tx_hex, block_hash FROM transactions WHERE block_hash = ANY(SELECT hash FROM blocks WHERE id >= $1 ORDER BY id LIMIT $2)', offset, limit)
            blocks = await connection.fetch(f'SELECT * FROM blocks WHERE id >= $1 ORDER BY id LIMIT $2', offset, limit)

        index = {block['hash']: [] for block in blocks}
        for transaction in transactions:
            index[transaction['block_hash']].append(transaction['tx_hex'])

        result = []
        size = 0
        for block in blocks:
            block = normalize_block(block)
            block_hash = block['hash']
            txs = OLD_BLOCKS_TRANSACTIONS_ORDER.get(block_hash) or index[block_hash]
            size += sum(len(tx) for tx in txs)
            if size > MAX_BLOCK_SIZE_HEX * 8:
                break
            result.append({
                'block': block,
                'transactions': txs
            })
        return result

    async def get_block_by_id(self, block_id: int) -> dict:
        async with self.pool.acquire() as connection:
            block = await connection.fetchrow('SELECT * FROM blocks WHERE id = $1', block_id)
        return normalize_block(block) if block is not None else None

    async def get_block_transactions(self, block_hash: str, check_signatures: bool = True, hex_only: bool = False) -> List[Union[Transaction, CoinbaseTransaction]]:
        async with self.pool.acquire() as connection:
            txs = await connection.fetch('SELECT tx_hex FROM transactions WHERE block_hash = $1', block_hash)
        return [tx['tx_hex'] if hex_only else await Transaction.from_hex(tx['tx_hex'], check_signatures) for tx in txs]

    async def get_block_nice_transactions(self, block_hash: str) -> List[dict]:
        async with self.pool.acquire() as connection:
            txs = await connection.fetch('SELECT tx_hash, inputs_addresses FROM transactions WHERE block_hash = $1', block_hash)
        return [{'hash': tx['tx_hash'], 'is_coinbase': not tx['inputs_addresses']} for tx in txs]

    async def add_unspent_outputs(self, outputs: List[Tuple[str, int]]) -> None:
        if not outputs:
            return
        async with self.pool.acquire() as connection:
            if len(outputs[0]) == 2:
                await connection.executemany('INSERT INTO unspent_outputs (tx_hash, index) VALUES ($1, $2)', outputs)
            elif len(outputs[0]) == 3:
                await connection.executemany('INSERT INTO unspent_outputs (tx_hash, index, address) VALUES ($1, $2, $3)', outputs)

    async def add_pending_spent_outputs(self, outputs: List[Tuple[str, int]]) -> None:
        async with self.pool.acquire() as connection:
            await connection.executemany('INSERT INTO pending_spent_outputs (tx_hash, index) VALUES ($1, $2)', outputs)

    async def add_transactions_pending_spent_outputs(self, transactions: List[Transaction]) -> None:
        outputs = sum([[(tx_input.tx_hash, tx_input.index) for tx_input in transaction.inputs] for transaction in transactions], [])
        async with self.pool.acquire() as connection:
            await connection.executemany('INSERT INTO pending_spent_outputs (tx_hash, index) VALUES ($1, $2)', outputs)

    async def add_unspent_transactions_outputs(self, transactions: List[Transaction]) -> None:
        outputs = sum([[(transaction.hash(), index, output.address) for index, output in enumerate(transaction.outputs)] for transaction in transactions], [])
        await self.add_unspent_outputs(outputs)

    async def remove_unspent_outputs(self, transactions: List[Transaction]) -> None:
        inputs = sum([[(tx_input.tx_hash, tx_input.index) for tx_input in transaction.inputs] for transaction in transactions], [])
        try:
            async with self.pool.acquire() as connection:
                await connection.execute('DELETE FROM unspent_outputs WHERE (tx_hash, index) = ANY($1::tx_output[])', inputs)
        except:
            await self.remove_unspent_outputs(transactions)

    async def remove_pending_spent_outputs(self, transactions: List[Transaction]) -> None:
        inputs = sum([[(tx_input.tx_hash, tx_input.index) for tx_input in transaction.inputs] for transaction in transactions], [])
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM pending_spent_outputs WHERE (tx_hash, index) = ANY($1::tx_output[])', inputs)

    async def get_unspent_outputs(self, outputs: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
        async with self.pool.acquire() as connection:
            results = await connection.fetch('SELECT tx_hash, index FROM unspent_outputs WHERE (tx_hash, index) = ANY($1::tx_output[])', outputs)
            return [(row['tx_hash'], row['index']) for row in results]

    async def get_unspent_outputs_hash(self) -> str:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch('SELECT tx_hash, index FROM unspent_outputs ORDER BY tx_hash, index')
            return sha256(''.join(row['tx_hash'] + bytes([row['index']]).hex() for row in rows))

    async def get_pending_spent_outputs(self, outputs: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
        async with self.pool.acquire() as connection:
            results = await connection.fetch('SELECT tx_hash, index FROM pending_spent_outputs WHERE (tx_hash, index) = ANY($1::tx_output[])', outputs)
            return [(row['tx_hash'], row['index']) for row in results]

    async def set_unspent_outputs_addresses(self):
        assert self.is_indexed, 'cannot set unspent outputs addresses if addresses are not indexed'
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE unspent_outputs SET address = (SELECT outputs_addresses[index + 1] FROM transactions where tx_hash = unspent_outputs.tx_hash)")

    async def get_unspent_outputs_from_all_transactions(self):
        async with self.pool.acquire() as connection:
            txs = await connection.fetch('SELECT tx_hex, blocks.id AS block_no FROM transactions INNER JOIN blocks ON (transactions.block_hash = blocks.hash) ORDER BY blocks.id ASC')
        outputs = set()
        last_block_no = 0
        for tx in txs:
            if tx['block_no'] != last_block_no:
                last_block_no = tx['block_no']
                print(f'{len(outputs)} utxos at block {last_block_no - 1}')
            tx_hash = sha256(tx['tx_hex'])
            transaction = await Transaction.from_hex(tx['tx_hex'], check_signatures=False)
            if isinstance(transaction, Transaction):
                outputs = outputs.difference({(tx_input.tx_hash, tx_input.index) for tx_input in transaction.inputs})
            outputs.update({(tx_hash, index) for index in range(len(transaction.outputs))})  # append
        return list(outputs)

    async def get_address_transactions(self, address: str, check_pending_txs: bool = False, check_signatures: bool = False, limit: int = 50) -> List[Union[Transaction, CoinbaseTransaction]]:
        point = string_to_point(address)
        search = ['%' + point_to_bytes(string_to_point(address), address_format).hex() + '%' for address_format in list(AddressFormat)]
        addresses = [point_to_string(point, address_format) for address_format in list(AddressFormat)]
        async with self.pool.acquire() as connection:
            txs = await connection.fetch('SELECT tx_hex, blocks.id AS block_no FROM transactions INNER JOIN blocks ON (transactions.block_hash = blocks.hash) WHERE $1 && inputs_addresses OR $1 && outputs_addresses ORDER BY block_no DESC LIMIT $2', addresses, limit)
            if check_pending_txs:
                txs = await connection.fetch("SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE ANY($1) OR $2 && inputs_addresses", search, addresses) + txs
        return [await Transaction.from_hex(tx['tx_hex'], check_signatures) for tx in txs]

    async def get_address_pending_transactions(self, address: str, check_signatures: bool = False) -> List[Union[Transaction, CoinbaseTransaction]]:
        point = string_to_point(address)
        search = ['%' + point_to_bytes(string_to_point(address), address_format).hex() + '%' for address_format in list(AddressFormat)]
        addresses = [point_to_string(point, address_format) for address_format in list(AddressFormat)]
        async with self.pool.acquire() as connection:
            txs = await connection.fetch("SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE ANY($1) OR $2 && inputs_addresses", search, addresses)
        return [await Transaction.from_hex(tx['tx_hex'], check_signatures) for tx in txs]

    async def get_address_pending_spent_outputs(self, address: str, check_signatures: bool = False) -> List[Union[Transaction, CoinbaseTransaction]]:
        point = string_to_point(address)
        addresses = [point_to_string(point, address_format) for address_format in list(AddressFormat)]
        async with self.pool.acquire() as connection:
            txs = await connection.fetch("SELECT tx_hex FROM pending_transactions WHERE $1 && inputs_addresses", addresses)
            txs = [await Transaction.from_hex(tx['tx_hex'], check_signatures) for tx in txs]
        return sum([[{'tx_hash': tx_input.tx_hash, 'index': tx_input.index} for tx_input in tx.inputs] for tx in txs], [])

    async def get_spendable_outputs(self, address: str, check_pending_txs: bool = False) -> List[TransactionInput]:
        point = string_to_point(address)
        search = ['%'+point_to_bytes(string_to_point(address), address_format).hex()+'%' for address_format in list(AddressFormat)]
        addresses = [point_to_string(point, address_format) for address_format in list(AddressFormat)]
        addresses.reverse()
        search.reverse()
        async with self.pool.acquire() as connection:
            if await connection.fetchrow('SELECT tx_hash, index FROM unspent_outputs WHERE address IS NULL') is not None:
                await self.set_unspent_outputs_addresses()
            if not check_pending_txs:
                unspent_outputs = await connection.fetch('SELECT unspent_outputs.tx_hash, index, transactions.outputs_amounts[index + 1] AS amount FROM unspent_outputs INNER JOIN transactions ON (transactions.tx_hash = unspent_outputs.tx_hash) WHERE address = ANY($1)', addresses)
            else:
                unspent_outputs = await connection.fetch('SELECT unspent_outputs.tx_hash, index, transactions.outputs_amounts[index + 1] AS amount FROM unspent_outputs INNER JOIN transactions ON (transactions.tx_hash = unspent_outputs.tx_hash) WHERE address = ANY($1) AND CONCAT(unspent_outputs.tx_hash, unspent_outputs.index) != ALL(SELECT CONCAT(pending_spent_outputs.tx_hash, pending_spent_outputs.index) FROM pending_spent_outputs)', addresses, timeout=60)
        return [TransactionInput(tx_hash, index, amount=Decimal(amount) / SMALLEST, public_key=point) for tx_hash, index, amount in unspent_outputs]

    async def get_address_balance(self, address: str, check_pending_txs: bool = False) -> Decimal:
        point = string_to_point(address)
        search = ['%'+point_to_bytes(string_to_point(address), address_format).hex()+'%' for address_format in list(AddressFormat)]
        addresses = [point_to_string(point, address_format) for address_format in list(AddressFormat)]
        tx_inputs = await self.get_spendable_outputs(address, check_pending_txs=check_pending_txs)
        balance = sum([tx_input.amount for tx_input in tx_inputs], Decimal(0))
        if check_pending_txs:
            async with self.pool.acquire() as connection:
                txs = await connection.fetch('SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE ANY($1)', search)
            for tx in txs:
                tx = await Transaction.from_hex(tx['tx_hex'], check_signatures=False)
                for i, tx_output in enumerate(tx.outputs):
                    if tx_output.address in addresses:
                        balance += tx_output.amount
        return balance

    async def get_address_spendable_outputs_delta(self, address: str, block_no: int) -> Tuple[List[TransactionInput], List[TransactionInput]]:
        point = string_to_point(address)
        addresses = [point_to_string(point, address_format) for address_format in list(AddressFormat)]
        async with self.pool.acquire() as connection:
            unspent_outputs = await connection.fetch('SELECT unspent_outputs.tx_hash, index, transactions.outputs_amounts[index + 1] AS amount FROM unspent_outputs INNER JOIN transactions ON (transactions.tx_hash = unspent_outputs.tx_hash) INNER JOIN blocks ON (blocks.hash = transactions.block_hash) WHERE unspent_outputs.address = ANY($1) AND blocks.id >= $2', addresses, block_no)
            spending_txs = await connection.fetch('SELECT tx_hex, blocks.id AS block_no FROM transactions INNER JOIN blocks ON (transactions.block_hash = blocks.hash) WHERE $1 = ANY(inputs_addresses) AND blocks.id >= $2 LIMIT $2', address, block_no)
        unspent_outputs = [TransactionInput(tx_hash, index, amount=Decimal(amount) / SMALLEST, public_key=point) for tx_hash, index, amount in unspent_outputs]
        spending_txs = [await Transaction.from_hex(tx['tx_hex'], False) for tx in spending_txs]
        spent_outputs = sum([tx.inputs for tx in spending_txs], [])
        return unspent_outputs, spent_outputs

    async def get_nice_transaction(self, tx_hash: str, address: str = None):
        async with self.pool.acquire() as connection:
            res = await connection.fetchrow('SELECT tx_hex, tx_hash, block_hash, inputs_addresses FROM transactions WHERE tx_hash = $1', tx_hash)
            if res is None:
                res = await connection.fetchrow('SELECT tx_hex, tx_hash, inputs_addresses FROM pending_transactions WHERE tx_hash = $1', tx_hash)
        if res is None:
            return None
        tx = await Transaction.from_hex(res['tx_hex'], False)
        if isinstance(tx, CoinbaseTransaction):
            transaction = {'is_coinbase': True, 'hash': res['tx_hash'], 'block_hash': res.get('block_hash')}
        else:
            delta = None
            if address is not None:
                public_key = string_to_point(address)
                delta = 0
                for i, tx_input in enumerate(tx.inputs):
                    if string_to_point(res['inputs_addresses'][i]) == public_key:
                        print('getting related output for delta')
                        delta -= await tx_input.get_amount()
                for tx_output in tx.outputs:
                    if tx_output.public_key == public_key:
                        delta += tx_output.amount
            transaction = {'is_coinbase': False, 'hash': res['tx_hash'], 'block_hash': res.get('block_hash'), 'message': tx.message.hex() if tx.message is not None else None, 'inputs': [], 'delta': delta, 'fees': await tx.get_fees()}
            for i, input in enumerate(tx.inputs):
                transaction['inputs'].append({
                    'index': input.index,
                    'tx_hash': input.tx_hash,
                    'address': res['inputs_addresses'][i],
                    'amount': await input.get_amount()
                })
        transaction['outputs'] = [{'address': output.address, 'amount': output.amount} for output in tx.outputs]
        return transaction
