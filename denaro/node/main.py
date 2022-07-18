import random
from asyncio import gather
from collections import deque
from os import environ

from asyncpg import UniqueViolationError
from fastapi import FastAPI, Body, Query
from httpx import TimeoutException
from icecream import ic
from starlette.background import BackgroundTasks
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded


from denaro.helpers import timestamp, sha256, transaction_to_json
from denaro.manager import create_block, get_difficulty, Manager, get_transactions_merkle_tree, \
    split_block_content, calculate_difficulty, clear_pending_transactions, block_to_bytes, get_transactions_merkle_tree_ordered
from denaro.node.nodes_manager import NodesManager, NodeInterface
from denaro.node.utils import ip_is_local
from denaro.transactions import Transaction, CoinbaseTransaction
from denaro import Database
from denaro.constants import VERSION, ENDIAN


limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
db: Database = None
NodesManager.init()
started = False
is_syncing = False
self_url = None

print = ic

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


async def propagate(path: str, args: dict, ignore_url=None):
    global self_url
    self_node = NodeInterface(self_url or '')
    ignore_node = NodeInterface(ignore_url or '')
    active_nodes = NodesManager.get_recent_nodes()
    zero_nodes = NodesManager.get_zero_nodes()
    send_nodes = \
        (random.choices(active_nodes, k=7) if len(active_nodes) > 7 else active_nodes) + \
        (random.choices(zero_nodes, k=3) if len(zero_nodes) > 3 else zero_nodes)
    aws = []
    for node_url in send_nodes:
        node_interface = NodeInterface(node_url)
        if node_interface.base_url == self_node.base_url or node_interface.base_url == ignore_node.base_url:
            continue
        aws.append(node_interface.request(path, args, self_node.url))
    for response in await gather(*aws, return_exceptions=True):
        print('node response: ', response)


async def create_blocks(blocks: list):
    _, last_block = await calculate_difficulty()
    last_block['id'] = last_block['id'] if last_block != {} else 0
    last_block['hash'] = last_block['hash'] if 'hash' in last_block else (30_06_2005).to_bytes(32, ENDIAN).hex()
    i = last_block['id'] + 1
    for block_info in blocks:
        block = block_info['block']
        txs_hex = block_info['transactions']
        txs = [await Transaction.from_hex(tx) for tx in txs_hex]
        for tx in txs:
            if isinstance(tx, CoinbaseTransaction):
                txs.remove(tx)
                break
        hex_txs = [tx.hex() for tx in txs]
        block['merkle_tree'] = get_transactions_merkle_tree(hex_txs) if i > 22500 else get_transactions_merkle_tree_ordered(hex_txs)
        block_content = block_to_bytes(last_block['hash'], block)

        if i <= 22500 and sha256(block_content) != block['hash'] and i != 17972:
            from itertools import permutations
            for l in permutations(hex_txs):
                _hex_txs = list(l)
                block['merkle_tree'] = get_transactions_merkle_tree_ordered(_hex_txs)
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
        nodes = NodesManager.get_recent_nodes()
        if not nodes:
            return
        node_url = random.choice(nodes)
    node_url = node_url.strip('/')
    _, last_block = await calculate_difficulty()
    i = await db.get_next_block_id()
    node_interface = NodeInterface(node_url)
    local_cache = None
    if last_block != {} and last_block['id'] > 500:
        remote_last_block = (await node_interface.get_block(i-1))['block']
        if remote_last_block['hash'] != last_block['hash']:
            print(remote_last_block['hash'])
            offset, limit = i - 500, 500
            remote_blocks = await node_interface.get_blocks(i-500, 500)
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
                    used_outputs = sum([[(tx_input.tx_hash, tx_input.index) for tx_input in getattr(await Transaction.from_hex(transaction), 'inputs', [])] for transaction in transactions_to_remove], [])
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
            blocks = await node_interface.get_blocks(i, limit)
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
        await _sync_blockchain(node_url)
    except Exception as e:
        print(e)
        return
    if node_url is not None:
        NodesManager.update_last_message(node_url)


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
async def root():
    return {"version": VERSION, "unspent_outputs_hash": await db.get_unspent_outputs_hash()}


@app.middleware("http")
async def middleware(request: Request, call_next):
    global started, self_url
    nodes = NodesManager.get_recent_nodes()
    hostname = request.base_url.hostname

    if 'Sender-Node' in request.headers:
        NodesManager.add_node(request.headers['Sender-Node'])

    if nodes and not started or (ip_is_local(hostname) or hostname == 'localhost'):
        try:
            node_url = nodes[0]
            #requests.get(f'{node_url}/add_node', {'url': })
            j = await NodesManager.request(f'{node_url}/get_nodes')
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
                await propagate('add_node', {'url': self_url})
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

transactions_cache = deque(maxlen=100)


@app.get("/push_tx")
@app.post("/push_tx")
async def push_tx(request: Request, background_tasks: BackgroundTasks, tx_hex: str = None, body=Body(False)):
    if body and tx_hex is None:
        tx_hex = body['tx_hex']
    tx = await Transaction.from_hex(tx_hex)
    try:
        assert tx.hash() not in transactions_cache
        if await db.add_pending_transaction(tx):
            if 'Sender-Node' in request.headers:
                NodesManager.update_last_message(request.headers['Sender-Node'])
            background_tasks.add_task(propagate, 'push_tx', {'tx_hex': tx_hex})
            transactions_cache.append(tx.hash())
            return {'ok': True, 'result': 'Transaction has been accepted'}
        else:
            return {'ok': False, 'error': 'Transaction has not been added'}
    except (UniqueViolationError, AssertionError):
        return {'ok': False, 'error': 'Transaction already present'}


@app.post("/push_block")
@app.get("/push_block")
@limiter.limit("3/minute")
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

    if 'Sender-Node' in request.headers:
        NodesManager.update_last_message(request.headers['Sender-Node'])

    background_tasks.add_task(propagate, 'push_block', {
        'block_content': block_content,
        'txs': [tx.hex() for tx in final_transactions] if len(final_transactions) < 10 else txs,
        'id': id
    })
    return {'ok': True}


@app.get("/sync_blockchain")
@limiter.limit("10/minute")
async def sync(request: Request, node_url: str = None):
    global is_syncing
    if is_syncing:
        return {'ok': False, 'error': 'Node is already syncing'}
    is_syncing = True
    await sync_blockchain(node_url)
    is_syncing = False


LAST_PENDING_TRANSACTIONS_CLEAN = [0]


@app.get("/get_mining_info")
async def get_mining_info(background_tasks: BackgroundTasks):
    Manager.difficulty = None
    difficulty, last_block = await get_difficulty()
    pending_transactions = await db.get_pending_transactions_limit(hex_only=True)
    pending_transactions = sorted(pending_transactions)
    if LAST_PENDING_TRANSACTIONS_CLEAN[0] < timestamp() - 600:
        print(LAST_PENDING_TRANSACTIONS_CLEAN[0])
        LAST_PENDING_TRANSACTIONS_CLEAN[0] = timestamp()
        background_tasks.add_task(clear_pending_transactions, pending_transactions)
    return {'ok': True, 'result': {
        'difficulty': difficulty,
        'last_block': last_block,
        'pending_transactions': pending_transactions[:10],
        'pending_transactions_hashes': [sha256(tx) for tx in pending_transactions],
        'merkle_root': get_transactions_merkle_tree(pending_transactions[:10])
    }}


@app.get("/get_address_info")
@limiter.limit("1/second")
async def get_address_info(request: Request, address: str, transactions_count_limit: int = Query(default=5, le=50), show_pending: bool = False, verify: bool = False):
    outputs = await db.get_spendable_outputs(address)
    balance = sum(output.amount for output in outputs)
    return {'ok': True, 'result': {
        'balance': "{:f}".format(balance),
        'spendable_outputs': [{'amount': "{:f}".format(output.amount), 'tx_hash': output.tx_hash, 'index': output.index} for output in outputs],
        'transactions': [await transaction_to_json(tx, verify, address) for tx in await db.get_address_transactions(address, limit=transactions_count_limit, check_signatures=True)] if transactions_count_limit > 0 else [],
        'pending_transactions': [await transaction_to_json(tx, verify, address) for tx in await db.get_address_pending_transactions(address, True)] if show_pending else None,
        'pending_spent_outputs': await db.get_address_pending_spent_outputs(address) if show_pending else None
    }}


@app.get("/add_node")
@limiter.limit("10/minute")
async def add_node(request: Request, url: str, background_tasks: BackgroundTasks):
    nodes = NodesManager.get_nodes()
    url = url.strip('/')
    if url == self_url:
        return {'ok': False, 'error': 'Recursively adding node'}
    if url in nodes:
        return {'ok': False, 'error': 'Node already present'}
    else:
        try:
            assert await NodesManager.is_node_working(url)
            background_tasks.add_task(propagate, 'add_node', {'url': url}, url)
            NodesManager.add_node(url)
            return {'ok': True, 'result': 'Node added'}
        except Exception as e:
            print(e)
            return {'ok': False, 'error': 'Could not add node'}


@app.get("/get_nodes")
async def get_nodes():
    return {'ok': True, 'result': NodesManager.get_recent_nodes()[:100]}


@app.get("/get_pending_transactions")
async def get_pending_transactions():
    return {'ok': True, 'result': [tx.hex() for tx in await db.get_pending_transactions_limit(1000)]}


@app.get("/get_transaction")
@limiter.limit("2/second")
async def get_transaction(request: Request, tx_hash: str, verify: bool = False):
    tx = await db.get_transaction(tx_hash) or await db.get_pending_transaction(tx_hash)
    if tx is None:
        return {'ok': False, 'error': 'Transaction not found'}
    transaction = await transaction_to_json(tx, verify)
    return {'ok': True, 'result': transaction}


@app.get("/get_block")
@limiter.limit("30/minute")
async def get_block(request: Request, block: str, full_transactions: bool = False):
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
@limiter.limit("10/minute")
async def get_blocks(request: Request, offset: int, limit: int = Query(default=..., le=1000)):
    blocks = await db.get_blocks(offset, limit)
    return {'ok': True, 'result': blocks}
