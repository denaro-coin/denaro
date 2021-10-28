import sys
import traceback
from datetime import datetime
from decimal import Decimal
from dateutil import parser
from typing import List, Union

import asyncpg
from asyncpg import Connection, Record, Pool
from icecream import ic

from .helpers import sha256, point_to_string, string_to_point, point_to_bytes
from .transactions import Transaction, CoinbaseTransaction, TransactionInput

_print = print
print = ic

class Database:
    connection: Connection = None
    credentials = {}
    instance = None
    pool: Pool = None

    @staticmethod
    async def create(user='denaro', password='', database='denaro', host='127.0.0.1'):
        self = Database()
        #self.connection = await asyncpg.connect(user=user, password=password, database=database, host=host)
        self.pool = await asyncpg.create_pool(
            user=user,
            password=password,
            database=database,
            host=host,
            command_timeout=6,
            min_size=3
        )
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
        tx_hex = transaction.hex()
        assert await transaction.verify()
        async with self.pool.acquire() as connection:
            await connection.fetch(
                'INSERT INTO pending_transactions (tx_hash, tx_hex, inputs_addresses, fees) VALUES ($1, $2, $3, $4)',
                sha256(tx_hex),
                tx_hex,
                [point_to_string(await tx_input.get_public_key()) for tx_input in transaction.inputs],
                transaction.fees
            )

    async def remove_pending_transaction(self, tx_hash: str):
        async with self.pool.acquire() as connection:
            await connection.fetch('DELETE FROM pending_transactions WHERE tx_hash = $1', tx_hash)

    async def remove_pending_transactions(self,):
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM pending_transactions')

    async def delete_blockchain(self):
        async with self.pool.acquire() as connection:
            await connection.execute('TRUNCATE transactions, blocks RESTART IDENTITY')

    async def reindex_blocks(self):
        async with self.pool.acquire() as connection:
            await connection.execute(f'ALTER SEQUENCE blocks_id_seq RESTART {await self.get_next_block_id()}')

    async def delete_block(self, id: int):
        async with self.pool.acquire() as connection:
            await connection.execute('DELETE FROM blocks WHERE id = $1', id)
            await connection.execute(f'ALTER SEQUENCE blocks_id_seq RESTART {await self.get_next_block_id()}')

    async def get_pending_transactions_limit(self, limit: int = 1000) -> List[Transaction]:
        async with self.pool.acquire() as connection:
            txs = await connection.fetch(f'SELECT tx_hex FROM pending_transactions ORDER BY fees DESC LIMIT {limit}')
            return [await Transaction.from_hex(tx['tx_hex']) for tx in txs]
            return [tx for tx in [await Transaction.from_hex(tx['tx_hex']) for tx in await stmt.fetch()] if await tx.verify()]

    async def add_transaction(self, transaction: Union[Transaction, CoinbaseTransaction], block_hash: str):
        tx_hex = transaction.hex()
        assert await transaction.verify()
        async with self.pool.acquire() as connection:
            stmt = await connection.prepare('INSERT INTO transactions (block_hash, tx_hash, tx_hex, inputs_addresses, fees) VALUES ($1, $2, $3, $4, $5)')
            await stmt.fetchval(
                block_hash,
                sha256(tx_hex),
                tx_hex,
                [point_to_string(await tx_input.get_public_key()) for tx_input in transaction.inputs] if isinstance(transaction, Transaction) else [],
                transaction.fees if isinstance(transaction, Transaction) else 0
            )

    async def add_block(self, block_hash: str, address: str, random: str, difficulty: Decimal, reward: Decimal, timestamp: Union[datetime, str]):
        async with self.pool.acquire() as connection:
            stmt = await connection.prepare('INSERT INTO blocks (hash, address, random, difficulty, reward, timestamp) VALUES ($1, $2, $3, $4, $5, $6)')
            await stmt.fetchval(
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
        #traceback.print_stack(file=sys.stdout)
        async with self.pool.acquire() as connection:
            res = await connection.fetchrow('SELECT tx_hex FROM transactions WHERE tx_hash = $1', tx_hash)
        return await Transaction.from_hex(res['tx_hex'], check_signatures) if res is not None else None

    async def get_transactions_by_contains(self, contains: str):
        async with self.pool.acquire() as connection:
            res = await connection.fetch('SELECT tx_hex FROM transactions WHERE tx_hex LIKE $1 AND tx_hash != $2', f"%{contains}%", contains)
        return [await Transaction.from_hex(res['tx_hex']) for res in res] if res is not None else None

    async def get_pending_transactions_by_contains(self, contains: str):
        async with self.pool.acquire() as connection:
            res = await connection.fetch('SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE $1 AND tx_hash != $2', f"%{contains}%", contains)
        return [await Transaction.from_hex(res['tx_hex']) for res in res] if res is not None else None

    async def get_next_block_id(self) -> int:
        async with self.pool.acquire() as connection:
            last_id = await connection.fetchval('SELECT id FROM blocks ORDER BY id DESC LIMIT 1', column=0)
        last_id = last_id if last_id is not None else 0
        return last_id + 1

    async def get_block(self, block_hash: str) -> Record:
        async with self.pool.acquire() as connection:
            return await connection.fetchrow('SELECT * FROM blocks WHERE hash = $1', block_hash)

    async def get_block_by_id(self, block_id: int) -> Record:
        async with self.pool.acquire() as connection:
            return await connection.fetchrow('SELECT * FROM blocks WHERE id = $1', block_id)

    async def get_block_transactions(self, block_hash: str) -> List[Record]:
        async with self.pool.acquire() as connection:
            return await connection.fetch('SELECT * FROM transactions WHERE block_hash = $1', block_hash)

    async def get_spendable_outputs(self, address: str, check_pending_txs: bool = False) -> List[TransactionInput]:
        async with self.pool.acquire() as connection:
            txs = await connection.fetch('SELECT tx_hex FROM transactions WHERE tx_hex LIKE $1', f"%{point_to_bytes(string_to_point(address)).hex()}%")
            spender_txs = await connection.fetch("SELECT tx_hex FROM transactions WHERE $1 = ANY(inputs_addresses)", point_to_bytes(string_to_point(address)).hex())
            if check_pending_txs:
                spender_txs += await connection.fetch("SELECT tx_hex FROM pending_transactions WHERE $1 = ANY(inputs_addresses)", point_to_bytes(string_to_point(address)).hex())
            inputs = []
            index = {}
            for tx in txs:
                used_outputs = []
                tx_hash = sha256(tx['tx_hex'])
                tx = await Transaction.from_hex(tx['tx_hex'], check_signatures=False)
                for i, tx_output in enumerate(tx.outputs):
                    if point_to_string(tx_output.public_key) == address and i not in used_outputs:
                        tx_input = TransactionInput(tx_hash, i)
                        tx_input.amount = tx_output.amount
                        index[tx_hash + str(i)] = tx_input
                        inputs.append(tx_input)

        for spender_tx in spender_txs:
            spender_tx = await Transaction.from_hex(spender_tx['tx_hex'], check_signatures=False)
            is_spender = False
            for tx_input in spender_tx.inputs:
                if tx_input.tx_hash + str(tx_input.index) in index:
                    used_outputs.append(tx_input.tx_hash + str(tx_input.index))
            if is_spender:
                continue

        final = []
        for tx_input in inputs:
            if tx_input.tx_hash + str(tx_input.index) not in used_outputs:
                final.append(tx_input)

        return final

    async def get_address_balance(self, address: str, check_pending_txs: bool = False) -> Decimal:
        balance = Decimal(0)
        for input in await self.get_spendable_outputs(address, check_pending_txs=check_pending_txs):
            balance += input.amount
        if check_pending_txs:
            async with self.pool.acquire() as connection:
                txs = await connection.fetch('SELECT tx_hex FROM pending_transactions WHERE tx_hex LIKE $1',
                                             f"%{point_to_bytes(string_to_point(address)).hex()}%")
                for tx in txs:
                    tx = await Transaction.from_hex(tx['tx_hex'], check_signatures=False)
                    for i, tx_output in enumerate(tx.outputs):
                        if point_to_string(tx_output.public_key) == address:
                            balance += tx_output.amount
        return balance
