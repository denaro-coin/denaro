import json
import os
from os.path import dirname, exists

import httpx
import pickledb
import requests

path = dirname(os.path.realpath(__file__)) + '/nodes.json'
if not exists(path):
    json.dump({}, open(path, 'wt'))
db = pickledb.load(path, True)


class NodesManager:
    nodes: list = None
    db = db

    timeout = httpx.Timeout(3.0)
    client = httpx.Client(timeout=timeout)
    async_client = httpx.AsyncClient(timeout=timeout)

    @staticmethod
    def init():
        NodesManager.db._loaddb()
        NodesManager.nodes = NodesManager.db.get('nodes') or ['https://denaro-node.gaetano.eu.org']

    @staticmethod
    def sync():
        NodesManager.db.set('nodes', NodesManager.nodes)

    @staticmethod
    async def request(url: str, method: str = 'GET', **kwargs):
        async with NodesManager.async_client.stream(method, url, **kwargs) as response:
            async for chunk in response.aiter_text():
                res = chunk
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
        NodesManager.init()
        NodesManager.nodes.append(node)
        NodesManager.sync()

    @staticmethod
    def get_nodes():
        NodesManager.init()
        NodesManager.nodes = list(dict.fromkeys(NodesManager.nodes))
        NodesManager.sync()
        return NodesManager.nodes


class NodeInterface:
    def __init__(self, url: str):
        self.url = url.strip('/')

    def get_block(self, block_no: int):
        r = requests.get(f'{self.url}/get_block', {'block': block_no}, timeout=10)
        res = r.json()
        return res['result']

    def get_blocks(self, offset: int, limit: int):
        r = requests.get(f'{self.url}/get_blocks', {'offset': offset, 'limit': limit}, timeout=10)
        res = r.json()
        return res['result']

    async def request(self, path: str, data: dict, sender_node: str):
        headers = {'Sender-Node': sender_node}
        if path in ('push_block', 'push_tx'):
            r = await NodesManager.request(f'{self.url}/{path}', method='POST', json=data, headers=headers)
        else:
            r = await NodesManager.request(f'{self.url}/{path}', params=data, headers=headers)
        return r
