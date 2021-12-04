import os

import pickledb
import requests


class NodesManager:
    nodes: list = None
    db = pickledb.load(os.path.dirname(os.path.realpath(__file__)) + '/nodes.json', True)

    @staticmethod
    def init():
        NodesManager.db._loaddb()
        NodesManager.nodes = NodesManager.db.get('nodes') or ['https://denaro-node.gaetano.eu.org']

    @staticmethod
    def sync():
        NodesManager.db.set('nodes', NodesManager.nodes)

    @staticmethod
    def is_node_working(node: str):
        try:
            r = requests.get(node, timeout=5)
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
