import hashlib
import sys
import time
from math import ceil
from multiprocessing import Process

import requests

from denaro.constants import ENDIAN
from denaro.helpers import string_to_bytes, timestamp


def get_transactions_merkle_tree(transactions):
    return hashlib.sha256(b''.join(bytes.fromhex(transaction) for transaction in transactions)).hexdigest()


NODE = sys.argv[3].strip('/')+'/' if len(sys.argv) >= 4 else 'http://localhost:3006/'


def run(start: int = 0, step: int = 1, res: dict = None):
    difficulty = res['difficulty']
    decimal = difficulty % 1
    last_block = res['last_block']
    last_block['hash'] = last_block['hash'] if 'hash' in last_block else (30_06_2005).to_bytes(32, ENDIAN).hex()
    last_block['id'] = last_block['id'] if 'id' in last_block else 0
    chunk = last_block['hash'][-int(difficulty):]

    charset = '0123456789abcdef'
    if decimal > 0:
        count = ceil(16 * (1 - decimal))
        charset = charset[:count]
        idifficulty = int(difficulty)

        def check_block_is_valid(block_content: bytes) -> bool:
            block_hash = hashlib.sha256(block_content).hexdigest()
            return block_hash.startswith(chunk) and block_hash[idifficulty] in charset
    else:
        def check_block_is_valid(block_content: bytes) -> bool:
            return hashlib.sha256(block_content).hexdigest().startswith(chunk)

    address = sys.argv[1]
    address_bytes = string_to_bytes(address)
    t = time.time()
    i = start
    a = timestamp()
    txs = res['pending_transactions_hashes']
    merkle_tree = get_transactions_merkle_tree(txs)
    assert all(len(tx) == 64 for tx in txs)
    if start == 0:
        print(f'difficulty: {difficulty}')
        print(f'block number: {last_block["id"]}')
        print(f'Confirming {len(txs)} transactions')
    prefix = bytes.fromhex(last_block['hash']) + address_bytes + bytes.fromhex(merkle_tree) + a.to_bytes(4, byteorder=ENDIAN) + int(difficulty * 10).to_bytes(2, ENDIAN)
    if len(address_bytes) == 33:
        prefix = (2).to_bytes(1, ENDIAN) + prefix
    while True:
        found = True
        check = 5000000 * step
        while not check_block_is_valid(_hex := prefix + i.to_bytes(4, ENDIAN)):
            if ((i := i + step) - start) % check == 0:
                elapsed_time = time.time() - t
                print(f'Worker {start + 1}: ' + str(int(i / step / elapsed_time / 1000)) + 'k hash/s')
                if elapsed_time > 90:
                    found = False
                    break
        if found:
            print(_hex.hex())
            print(','.join(txs))
            r = requests.post(NODE + 'push_block', json={
                'block_content': _hex.hex(),
                'txs': txs,
                'id': last_block["id"] + 1
            }, timeout=20 + int((len(txs) or 1) / 3))
            print(res := r.json())
            if res['ok']:
                print('BLOCK MINED\n\n')
            exit()


def worker(start: int, step: int, res: dict):
    while True:
        try:
            run(start, step, res)
        except Exception:
            raise
            time.sleep(3)


if __name__ == '__main__':
    workers = int(sys.argv[2]) if len(sys.argv) >= 3 else 1
    while True:
        print(f'Starting {workers} workers')
        res = None
        while res is None:
            try:
                r = requests.get(NODE + 'get_mining_info', timeout=5)
                res = r.json()['result']
            except Exception as e:
                print(e)
                time.sleep(1)
                pass
        processes = []
        for i in range(1, workers + 1):
            print(f'Starting worker n.{i}')
            p = Process(target=worker, daemon=True, args=(i-1, workers, res))
            p.start()
            processes.append(p)
        elapsed_seconds = 0
        while all(p.is_alive() for p in processes):
            time.sleep(1)
            elapsed_seconds += 1
            if elapsed_seconds > 100:
                break
        for p in processes:
            p.kill()
