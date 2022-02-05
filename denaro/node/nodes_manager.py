import json
import os
from os.path import dirname, exists

from eventlet.timeout import Timeout
import httpx as httpx
import pickledb
import requests

path = dirname(os.path.realpath(__file__)) + '/nodes.json'
if not exists(path):
    json.dump({}, open(path, 'wt'))
db = pickledb.load(path, True)


class NodesManager:
    nodes: list = None
    db = db

    timeout = httpx.Timeout(1.0, connect=1.0, read=1.0)
    client = httpx.Client(timeout=timeout)

    @staticmethod
    def init():
        NodesManager.db._loaddb()
        NodesManager.nodes = NodesManager.db.get('nodes') or ['https://denaro-node.gaetano.eu.org']

    @staticmethod
    def sync():
        NodesManager.db.set('nodes', NodesManager.nodes)

    @staticmethod
    async def is_node_working(node: str):
        try:
            with Timeout(5, False):
                r = NodesManager.client.get(node)
            r.json()
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
