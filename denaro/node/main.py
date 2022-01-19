import ipaddress
import random
from os import environ
from typing import Union

import requests
from asyncpg import UniqueViolationError
from fastapi import FastAPI, Body
from icecream import ic
from requests import ReadTimeout
from starlette.background import BackgroundTasks
from starlette.requests import Request
from starlette.responses import JSONResponse

from denaro.helpers import timestamp, sha256, transaction_to_json
from denaro.manager import create_block, get_difficulty, Manager, get_transactions_merkle_tree, check_block_is_valid, \
    split_block_content, calculate_difficulty, clear_pending_transactions, block_to_bytes, get_transactions_merkle_tree_ordered
from denaro.node.nodes_manager import NodesManager, NodeInterface
from denaro.transactions import Transaction, CoinbaseTransaction
from denaro import Database
from denaro.constants import VERSION, ENDIAN

app = FastAPI()
db: Database = None
NodesManager.init()
nodes = NodesManager.get_nodes()
started = False
self_url = None

print = ic


def ip_is_local(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except:
        return False
    networks = [
        '10.0.0.0/8',
        '172.16.0.0/12',
        '192.168.0.0/16',
        '0.0.0.0/8',
        '100.64.0.0/10',
        '127.0.0.0/8',
        '169.254.0.0/16',
        '192.0.0.0/24',
        '192.0.2.0/24',
        '192.88.99.0/24',
        '198.18.0.0/15',
        '198.51.100.0/24',
        '203.0.113.0/24',
        '224.0.0.0/4',
        '233.252.0.0/24',
        '240.0.0.0/4',
        '255.255.255.255/32'
    ]
    for network in networks:
        if addr in ipaddress.ip_network(network):
            return True
    return False


def propagate(path: str, args: dict, ignore=None):
    global self_url
    nodes = NodesManager.get_nodes()
    print(args)
    for node_url in random.choices(nodes, k=5) if len(nodes) > 5 else nodes:
        _node_url = node_url
        node_url = node_url.strip('/')
        node_base_url = node_url.replace('http://', '', 1).replace('https://', '', 1)
        if (
            self_url and node_base_url == self_url.replace('http://', '', 1).replace('https://', '', 1)
        ) or (
            ignore and node_base_url == ignore.replace('http://', '', 1).replace('https://', '', 1)
        ):
            continue
        try:
            if path == 'push_block':
                r = requests.post(f'{node_url}/{path}', json=args, timeout=20, headers={'Sender-Node': self_url})
            else:
                r = requests.get(f'{node_url}/{path}', args, timeout=5, headers={'Sender-Node': self_url})
            print('node response: ', r.json())
        except Exception as e:
            print(e)
            if not isinstance(e, ReadTimeout):
                NodesManager.get_nodes().remove(_node_url)
            NodesManager.sync()


async def create_blocks(blocks: list):
    _, last_block = await calculate_difficulty()
    last_block['id'] = last_block['id'] if last_block != {} else 0
    last_block['hash'] = last_block['hash'] if 'hash' in last_block else (30_06_2005).to_bytes(32, ENDIAN).hex()
    i = last_block['id'] + 1
    for block_info in blocks:
        block = block_info['block']
        txs_hex = block_info['transactions']
        txs = merkle_tree_txs = [await Transaction.from_hex(tx) for tx in txs_hex]
        for tx in txs:
            if isinstance(tx, CoinbaseTransaction):
                txs.remove(tx)
                break
        merkle_tree_txs = [tx.hex() for tx in merkle_tree_txs]
        block['merkle_tree'] = get_transactions_merkle_tree(txs) if i > 22500 else get_transactions_merkle_tree_ordered(
            txs)
        block_content = block_to_bytes(last_block['hash'], block)

        if i <= 22500:
            from itertools import permutations
            for l in permutations(merkle_tree_txs):
                txs = list(l)
                block['merkle_tree'] = get_transactions_merkle_tree_ordered(txs)
                block_content = block_to_bytes(last_block['hash'], block)
                if sha256(block_content) == block['hash']:
                    break
        assert i == block['id']
        if not await create_block(block_content.hex(), txs, last_block):
            return False
        last_block = block
        i += 1
    return True


async def _sync_blockchain(node_url: str = None):
    print('sync blockchain')
    if node_url is None:
        nodes = NodesManager.get_nodes()
        if not nodes:
            return
        node_url = random.choice(nodes)
    node_url = node_url.strip('/')
    _, last_block = await calculate_difficulty()
    i = await db.get_next_block_id()
    node_interface = NodeInterface(node_url)
    if last_block != {} and last_block['id'] > 500:
        remote_last_block = node_interface.get_block(i-1)['block']
        local_cache = None
        if remote_last_block['hash'] != last_block['hash']:
            print(remote_last_block['hash'])
            offset, limit = i - 500, 500
            remote_blocks = node_interface.get_blocks(i-500, 500)
            local_blocks = await db.get_blocks(offset, limit)
            local_blocks.reverse()
            remote_blocks.reverse()
            print(len(remote_blocks), len(local_blocks))
            if len(local_blocks) > len(remote_blocks):
                return
            for n, local_block in enumerate(local_blocks):
                if local_block['block']['hash'] == remote_blocks[n]['block']['hash']:
                    print(local_block, remote_blocks[n])
                    local_cache = local_blocks[:n]
                    local_cache.reverse()
                    last_common_block = i = local_block['block']['id']
                    blocks_to_remove = await db.get_blocks(last_common_block + 1, 500)
                    transactions_to_remove = sum([block_to_remove['transactions'] for block_to_remove in blocks_to_remove], [])
                    used_outputs = sum([[(tx_input.tx_hash, tx_input.index) for tx_input in (await Transaction.from_hex(transaction)).inputs] for transaction in transactions_to_remove], [])
                    await db.delete_blocks(last_common_block)
                    await db.add_unspent_outputs(used_outputs)
                    for tx in transactions_to_remove:
                        await db.add_pending_transaction(await Transaction.from_hex(tx))
                    print([c['block']['id'] for c in local_cache])
                    break

    #return
    limit = 1000
    while True:
        i = await db.get_next_block_id()
        try:
            blocks = node_interface.get_blocks(i, limit)
        except Exception as e:
            print(e)
            #NodesManager.get_nodes().remove(node_url)
            NodesManager.sync()
            break
        if not blocks:
            print('syncing complete')
            return
        try:
            assert await create_blocks(blocks)
        except Exception as e:
            print(e)
            if local_cache is not None:
                await db.delete_blocks(last_common_block)
                await create_blocks(local_cache)
            return


async def sync_blockchain(node_url: str = None):
    try:
        return await _sync_blockchain(node_url)
    except Exception as e:
        print(e)
        pass


@app.on_event("startup")
async def startup():
    global db
    db = await Database.create(
        user=environ.get('DENARO_DATABASE_USER', 'denaro'),
        password=environ.get('DENARO_DATABASE_PASSWORD', ''),
        database=environ.get('DENARO_DATABASE_NAME', 'denaro'),
        host=environ.get('DENARO_DATABASE_HOST', None)
    )


@app.get("/")
def read_root():
    return {"version": VERSION, "timestamp": timestamp()}


@app.middleware("http")
async def middleware(request: Request, call_next):
    global started, self_url, synced
    nodes = NodesManager.get_nodes()
    hostname = request.base_url.hostname

    if 'Sender-Node' in request.headers:
        NodesManager.add_node(request.headers['Sender-Node'])

    if nodes and not started or (ip_is_local(hostname) or hostname == 'localhost'):
        try:
            node_url = nodes[0]
            #requests.get(f'{node_url}/add_node', {'url': })
            r = requests.get(f'{node_url}/get_nodes')
            j = r.json()
            nodes.extend(j['result'])
            NodesManager.sync()
        except:
            pass

        if not (ip_is_local(hostname) or hostname == 'localhost'):
            started = True

            self_url = str(request.base_url).strip('/')
            try:
                nodes.remove(self_url)
            except ValueError:
                pass
            try:
                nodes.remove(self_url.replace("http://", "https://"))
            except ValueError:
                pass

            NodesManager.sync()

            try:
                propagate('add_node', {'url': self_url})
            except:
                pass
    try:
        response = await call_next(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except:
        raise
        return {'ok': False, 'error': 'Internal error'}


@app.exception_handler(Exception)
async def exception_handler(request: Request, e: Exception):
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": f"Uncaught {type(e).__name__} exception"},
    )


@app.get("/push_tx")
async def push_tx(tx_hex: str, background_tasks: BackgroundTasks):
    tx = await Transaction.from_hex(tx_hex)
    try:
        if await db.add_pending_transaction(tx):
            background_tasks.add_task(propagate, 'push_tx', {'tx_hex': tx_hex})
            return {'ok': True, 'result': 'Transaction has been accepted'}
        else:
            return {'ok': False, 'error': 'Transaction has not been added'}
    except UniqueViolationError:
        return {'ok': False, 'error': 'Transaction already present'}


@app.post("/push_block")
@app.get("/push_block")
async def push_block(request: Request, background_tasks: BackgroundTasks, block_content: str = '', txs='', body=Body(False), id: int = None):
    if body:
        txs = body['txs']
        if 'block_content' in body:
            block_content = body['block_content']
    if isinstance(txs, str):
        txs = txs.split(',')
        if txs == ['']:
            txs = []
    previous_hash = split_block_content(block_content)[0]
    next_block_id = await db.get_next_block_id()
    if id is None:
        previous_block = await db.get_block(previous_hash)
        if previous_block is None:
            if 'Sender-Node' in request.headers:
                background_tasks.add_task(sync_blockchain, request.headers['Sender-Node'])
                return {'ok': False,
                        'error': 'Previous hash not found, had to sync according to sender node, block may have been accepted'}
            else:
                return {'ok': False, 'error': 'Previous hash not found'}
        id = previous_block['id'] + 1
    if next_block_id < id:
        background_tasks.add_task(sync_blockchain, request.headers['Sender-Node'] if 'Sender-Node' in request.headers else None)
        return {'ok': False, 'error': 'Blocks missing, had to sync according to sender node, block may have been accepted'}
    if next_block_id > id:
        return {'ok': False, 'error': 'Too old block'}
    final_transactions = []
    hashes = []
    for tx_hex in txs:
        if len(tx_hex) == 64:  # it's an hash
            hashes.append(tx_hex)
        else:
            final_transactions.append(await Transaction.from_hex(tx_hex))
    if hashes:
        pending_transactions = await db.get_pending_transactions_by_hash(hashes)
        if len(pending_transactions) < len(hashes):  # one or more tx not found
            if 'Sender-Node' in request.headers:
                background_tasks.add_task(sync_blockchain, request.headers['Sender-Node'])
                return {'ok': False,
                        'error': 'Transaction hash not found, had to sync according to sender node, block may have been accepted'}
            else:
                return {'ok': False, 'error': 'Transaction hash not found'}
        final_transactions.extend(pending_transactions)
    if not await create_block(block_content, final_transactions):
        return {'ok': False}
    background_tasks.add_task(propagate, 'push_block', {
        'block_content': block_content,
        'txs': [tx.hex() for tx in final_transactions] if len(final_transactions) < 10 else txs,
        'id': id
    })
    return {'ok': True}


@app.get("/sync_blockchain")
async def sync(node_url: str = None):
    await sync_blockchain(node_url)


@app.get("/get_mining_info")
async def get_mining_info(background_tasks: BackgroundTasks):
    Manager.difficulty = None
    difficulty, last_block = await get_difficulty()
    pending_transactions = await db.get_pending_transactions_limit(1000, True)
    if random.randint(0, 10 + len(pending_transactions)) == 0:
        background_tasks.add_task(clear_pending_transactions)
    return {'ok': True, 'result': {
        'difficulty': difficulty,
        'last_block': last_block,
        'pending_transactions': pending_transactions[:10],
        'pending_transactions_hashes': (sha256(tx) for tx in pending_transactions),
        'merkle_root': get_transactions_merkle_tree(pending_transactions[:10])
    }}


@app.get("/get_address_info")
async def get_address_info(address: str):
    outputs = await db.get_spendable_outputs(address)
    balance = sum(output.amount for output in outputs)
    return {'ok': True, 'result': {
        'balance': balance,
        'spendable_outputs': [{'amount': output.amount, 'tx_hash': output.tx_hash, 'index': output.index} for output in
                              outputs]
    }}


@app.get("/add_node")
async def add_node(url: str, background_tasks: BackgroundTasks):
    nodes = NodesManager.get_nodes()
    url = url.strip('/')
    if url == self_url:
        return {'ok': False, 'error': 'Recursively adding node'}
    if url in nodes:
        return {'ok': False, 'error': 'Node already present'}
    else:
        try:
            assert NodesManager.is_node_working(url)
            background_tasks.add_task(propagate, 'add_node', {'url': url}, url)
            NodesManager.add_node(url)
            return {'ok': True, 'result': 'Node added'}
        except Exception as e:
            print(e)
            return {'ok': False, 'error': 'Could not add node'}


@app.get("/get_nodes")
async def get_nodes():
    nodes = NodesManager.get_nodes()
    return {'ok': True, 'result': nodes}


@app.get("/get_pending_transactions")
async def get_pending_transactions():
    return {'ok': True, 'result': [tx.hex() for tx in await db.get_pending_transactions_limit(1000)]}


@app.get("/get_transaction")
async def get_transaction(tx_hash: str, verify: bool = False):
    tx = await db.get_transaction(tx_hash) or await db.get_pending_transaction(tx_hash)
    if tx is None:
        return {'ok': False, 'error': 'Transaction not found'}
    transaction = await transaction_to_json(tx, verify)
    return {'ok': True, 'result': transaction}


@app.get("/get_block")
async def get_block(block: str, full_transactions: bool = False):
    if block.isdecimal():
        block_info = await db.get_block_by_id(int(block))
        if block_info is not None:
            block_hash = block_info['hash']
        else:
            return {'ok': False, 'error': 'Block not found'}
    else:
        block_hash = block
        block_info = await db.get_block(block_hash)
    if block_info:
        txs = await db.get_block_transactions(block_hash)
        return {'ok': True, 'result': {
            'block': block_info,
            'transactions': [tx.hex() for tx in txs],
            'full_transactions': [await transaction_to_json(tx) for tx in txs] if full_transactions else None
        }}
    else:
        return {'ok': False, 'error': 'Block not found'}


@app.get("/get_blocks")
async def get_blocks(offset: int, limit: int):
    blocks = await db.get_blocks(offset, limit)
    return {'ok': True, 'result': blocks}
