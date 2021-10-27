import asyncio
import sys
import time
import denaro
from denaro import node
from denaro.constants import ENDIAN
from denaro.manager import get_difficulty, check_block_is_valid, Manager, get_transactions_merkle_tree
from denaro.helpers import sha256, timestamp

from icecream import ic

from denaro.node.main import sync_blockchain

_print = print
print = ic


async def run():
    await denaro.node.main.create_database()
    db = denaro.node.main.db

    while True:
        await sync_blockchain()
        difficulty, last_block = await get_difficulty()
        last_block['hash'] = last_block['hash'] if 'hash' in last_block else (30_06_2005).to_bytes(32, ENDIAN).hex()
        print(difficulty)
        Manager.difficulty = None
        address = sys.argv[1]
        t = time.process_time()
        i = 0
        a = timestamp()
        txs = await db.get_pending_transactions_limit(1000)
        merkle_tree = get_transactions_merkle_tree(txs)
        prefix = bytes.fromhex(last_block['hash']) + bytes.fromhex(address) + bytes.fromhex(merkle_tree) + a.to_bytes(4, byteorder=ENDIAN) + int(difficulty * 10).to_bytes(2, ENDIAN)

        found = True
        while not await check_block_is_valid(_hex := prefix + i.to_bytes(4, ENDIAN)):
            i += 1
            if i % 1000000 == 0:
                elapsed_time = time.process_time() - t
                _print(str(i / elapsed_time) + ' hash/s')
                print(i)
                if elapsed_time > 150:
                    found = False
                    break
        if found:
            await sync_blockchain()
            print(await node.push_block(None, _hex.hex(), [tx.hex() for tx in txs]))
            Manager.difficulty = None
            if txs:
                for tx in txs:
                    await db.remove_pending_transaction(sha256(tx.hex()))

loop = asyncio.get_event_loop()
loop.run_until_complete(run())
