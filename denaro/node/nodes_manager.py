import json
import os
from os.path import dirname, exists

import httpx
import pickledb

from ..constants import MAX_BLOCK_SIZE_HEX
from ..helpers import timestamp

ACTIVE_NODES_DELTA = 60 * 60 * 24 * 7  # 7 days

path = dirname(os.path.realpath(__file__)) + '/nodes.json'
if not exists(path):
    json.dump({}, open(path, 'wt'))
db = pickledb.load(path, True)


class NodesManager:
    last_messages: dict = None
    nodes: list = None
    db = db

    timeout = httpx.Timeout(3)
    client = httpx.Client(timeout=timeout)
    async_client = httpx.AsyncClient(timeout=timeout)

    @staticmethod
    def init():
        NodesManager.db._loaddb()
        NodesManager.nodes = NodesManager.db.get('nodes') or ['https://denaro-node.gaetano.eu.org']
        NodesManager.last_messages = NodesManager.db.get('last_messages') or {'https://denaro-node.gaetano.eu.org': timestamp()}

    @staticmethod
    def sync():
        NodesManager.db.set('nodes', NodesManager.nodes)
        NodesManager.db.set('last_messages', NodesManager.last_messages)

    @staticmethod
    async def request(url: str, method: str = 'GET', **kwargs):
        async with NodesManager.async_client.stream(method, url, **kwargs) as response:
            res = ''
            async for chunk in response.aiter_text():
                res += chunk
                if len(res) > MAX_BLOCK_SIZE_HEX * 4:
                    break
        return json.loads(res)

    @staticmethod
    async def is_node_working(node: str):
        try:
            await NodesManager.request(node)
            return True
        except:
            return False

    @staticmethod
    def add_node(node: str):
        node = node.strip('/')
        if len(NodesManager.nodes) > 1000 or len(NodesManager.get_zero_nodes()) > 10:
            NodesManager.clear_dead_nodes()
        if len(NodesManager.nodes) > 1000:
            raise Exception('Too many nodes')
        NodesManager.init()
        NodesManager.nodes.append(node)
        NodesManager.sync()

    @staticmethod
    def get_nodes():
        NodesManager.init()
        NodesManager.nodes = list(dict.fromkeys(NodesManager.nodes))
        NodesManager.nodes = [node.strip('/') for node in NodesManager.nodes]
        NodesManager.sync()
        return NodesManager.nodes

    @staticmethod
    def get_recent_nodes():
        full_nodes = {node_url: NodesManager.get_last_message(node_url) for node_url in NodesManager.get_nodes()}
        return [item[0] for item in sorted(full_nodes.items(), key=lambda item: item[1], reverse=True) if item[1] > timestamp() - ACTIVE_NODES_DELTA]

    @staticmethod
    def get_zero_nodes():
        return [node for node in NodesManager.get_nodes() if NodesManager.get_last_message(node) == 0]

    @staticmethod
    def clear_dead_nodes():
        NodesManager.init()
        NodesManager.nodes = [node for node in NodesManager.get_nodes() if NodesManager.get_last_message(node) > 0]
        NodesManager.sync()

    @staticmethod
    def get_last_message(node_url: str):
        NodesManager.init()
        last_messages = NodesManager.last_messages
        return last_messages[node_url] if node_url in last_messages else 0

    @staticmethod
    def update_last_message(node_url: str):
        NodesManager.init()
        NodesManager.last_messages[node_url.strip('/')] = timestamp()
        NodesManager.sync()


class NodeInterface:
    def __init__(self, url: str):
        self.url = url.strip('/')
        self.base_url = self.url.replace('http://', '', 1).replace('https://', '', 1)

    async def get_block(self, block_no: int):
        res = await self.request(f'get_block', {'block': block_no})
        return res['result']

    async def get_blocks(self, offset: int, limit: int):
        res = await self.request(f'get_blocks', {'offset': offset, 'limit': limit})
        return res['result']

    async def request(self, path: str, data: dict, sender_node: str = ''):
        headers = {'Sender-Node': sender_node}
        if path in ('push_block', 'push_tx'):
            r = await NodesManager.request(f'{self.url}/{path}', method='POST', json=data, headers=headers, timeout=10)
        else:
            r = await NodesManager.request(f'{self.url}/{path}', params=data, headers=headers, timeout=10)
        return r
