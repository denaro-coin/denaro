import ipaddress
import random
from os import environ
from typing import List, Union

import requests
from fastapi import FastAPI, Body
from icecream import ic
from starlette.requests import Request

from denaro.helpers import timestamp, sha256
from denaro.manager import create_block, get_difficulty, Manager, get_transactions_merkle_tree, check_block_is_valid, \
    split_block_content, calculate_difficulty, clear_pending_transactions
from denaro.node.nodes_manager import NodesManager
from denaro.transactions import Transaction
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


async def propagate(path: str, args: dict, ignore = None):
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
            requests.get(f'{node_url}/{path}', args, timeout=5, headers={'Sender-Node': self_url})
        except Exception as e:
            print(e)
            NodesManager.get_nodes().remove(_node_url)
            NodesManager.sync()


async def sync_blockchain(node_url: str = None):
    print('sync blockchain')
    i = await db.get_next_block_id()
    if node_url is None:
        nodes = NodesManager.get_nodes()
        if not nodes:
            return
        node_url = nodes[0]
    node_url = node_url.strip('/')
    _, last_block = await get_difficulty()

    # fixme should validate blocks?
    while True:
        print(i)
        try:
            r = requests.get(f'{node_url}/get_block', {'block': i}, timeout=5)
            res = r.json()
            print(res)
        except Exception as e:
            print(e)
            NodesManager.get_nodes().remove(node_url)
            NodesManager.sync()
            break
        if 'ok' not in res or not res['ok']:
            print(res)
            break
        else:
            res = res['result']
        block = res['block']
        txs_hex = res['transactions']
        txs = [await Transaction.from_hex(tx) for tx in txs_hex]
        try:
            block_content = bytes.fromhex(last_block['hash'] if 'hash' in last_block else (30_06_2005).to_bytes(32, ENDIAN).hex()) + bytes.fromhex(block['address']) + bytes.fromhex(
                get_transactions_merkle_tree(txs_hex[1:])) + block['timestamp'].to_bytes(4, byteorder=ENDIAN) + int(block['difficulty'] * 10).to_bytes(2, ENDIAN) + block['random'].to_bytes(4, ENDIAN)
            if await create_block(block_content.hex(), txs, False) == False:
                break
        except:
            raise
            break
        i += 1
        last_block = block
        Manager.difficulty = None


@app.on_event("startup")
async def create_database():
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
    global started, self_url
    nodes = NodesManager.get_nodes()
    print(request.url)
    self_url = str(request.base_url).strip('/')
    print(self_url)
    try:
        nodes.remove(self_url)
    except ValueError:
        pass
    try:
        nodes.remove(self_url.replace("http://", "https://"))
    except ValueError:
        pass

    NodesManager.sync()

    if nodes and not started:
        await sync_blockchain()
        try:
            node_url = nodes[0]
            #requests.get(f'{node_url}/add_node', {'url': })
            r = requests.get(f'{node_url}/get_nodes')
            j = r.json()
            nodes.extend(j['result'])
            NodesManager.sync()
        except:
            pass

        hostname = request.base_url.hostname
        if not (ip_is_local(hostname) or hostname == 'localhost'):
            print('here')
            started = True

            try:
                print('here')
                await propagate('add_node', {'url': self_url})
                print('after propagate')
            except:
                pass
    try:
        response = await call_next(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except:
        raise
        return {'ok': False, 'error': 'Internal error'}


@app.get("/push_tx")
async def push_tx(tx_hex: str):
    try:
        tx = await Transaction.from_hex(tx_hex)
        await db.add_pending_transaction(tx)
        await propagate('push_tx', {'tx_hex': tx_hex})
        return {'ok': True, 'result': 'Transaction has been accepted'}
    except Exception as e:
        print(e)
        return {'ok': False, 'error': 'Sent HEX is not valid'}


@app.post("/push_block")
@app.get("/push_block")
async def push_block(request: Request, block_content: str = '', txs='', body=Body(False), id: int = None):
    if body:
        print(body)
        txs = body['txs']
        if 'block_content' in body:
            block_content = body['block_content']
    if isinstance(txs, str):
        txs = txs.split(',')
        if txs == ['']:
            txs = []
    next_block_id = await db.get_next_block_id()
    if id is not None:
        if next_block_id < id:
            await sync_blockchain(request.headers['Sender-Node'] if 'Sender-Node' in request.headers else None)
            if await db.get_next_block_id() != id:
                return {'ok': False, 'error': 'Could not sync blockchain'}
        if next_block_id > id:
            return {'ok': False, 'error': 'Too old block'}
    else:
        id = next_block_id
    try:
        added_transactions = await create_block(block_content, [await Transaction.from_hex(tx_hex) for tx_hex in txs])
        if added_transactions == False:
            if (True or await check_block_is_valid(block_content)) and id == next_block_id and (request and 'Sender-Node' in request.headers): # fixme
                previous_hash = split_block_content(block_content)[0]
                _, last_block = await calculate_difficulty()
                if previous_hash != last_block['hash']:
                    sender_node = request.headers['Sender-Node']
                    await db.delete_block(next_block_id - 1)
                    await sync_blockchain(sender_node)
                    return {'ok': False, 'error': 'Blockchain has been resynchronized according to sender node, block may have been accepted'}
            return {'ok': False}
        await propagate('push_block', {'block_content': block_content, 'txs': ','.join(txs),
                                       'id': id})
        for tx in added_transactions:
            await db.remove_pending_transaction(sha256(tx.hex()))
        return {'ok': True}
    except Exception as e:
        print(e)
        return {'ok': False}


@app.get("/sync_blockchain")
async def sync():
    await sync_blockchain()


@app.get("/push_full_block")
async def push_full_block(request, block_content: str, txs=[], id: int = None):
    return await push_block(request, block_content, txs, id)


@app.get("/get_mining_info")
async def get_mining_info():
    Manager.difficulty = None
    difficulty, last_block = await get_difficulty()
    print(last_block)
    last_block['timestamp'] = int(last_block['timestamp'].timestamp())
    await clear_pending_transactions()
    pending_transactions = await db.get_pending_transactions_limit(1000)
    return {'ok': True, 'result': {
        'difficulty': difficulty,
        'last_block': last_block,
        'pending_transactions': [tx.hex() for tx in pending_transactions],
        'merkle_root': get_transactions_merkle_tree(pending_transactions)
    }}


@app.get("/get_address_info")
async def get_address_info(address: str):
    try:
        balance = await db.get_address_balance(address)
        outputs = await db.get_spendable_outputs(address)
        return {'ok': True, 'result': {
            'balance': balance,
            'spendable_txs': [{'amount': output.amount, 'tx_hex': output.tx_hash, 'index': output.index} for output in outputs]
        }}
    except Exception as e:
        return {'ok': False, 'error': 'Not valid address'}


@app.get("/add_node")
async def add_node(url: str):
    nodes = NodesManager.get_nodes()
    url = url.strip('/')
    if url == self_url:
        return {'ok': False, 'error': 'Recursively adding node'}
    if url in nodes:
        return {'ok': False, 'error': 'Node already present'}
    else:
        try:
            assert NodesManager.is_node_working(url)
            await propagate('add_node', {'url': url}, url)
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


@app.get("/get_block")
async def get_block(block: str):
    if block.isdecimal():
        block_info = await db.get_block_by_id(int(block))
        if block_info is not None:
            block_hash = block_info['hash']
        else:
            return {'ok': False, 'error': 'Not found block'}
    else:
        block_hash = block
        block_info = await db.get_block(block_hash)
    if block_info:
        block_info = dict(block_info)
        block_info['timestamp'] = int(block_info['timestamp'].timestamp())
        txs = await db.get_block_transactions(block_hash)
        return {'ok': True, 'result': {
            'block': block_info,
            'transactions': [tx.hex() for tx in txs]
        }}
    else:
        return {'ok': False, 'error': 'Not found block'}
