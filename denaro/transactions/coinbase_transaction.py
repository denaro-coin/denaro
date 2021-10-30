from decimal import Decimal

from ..constants import ENDIAN, VERSION
from ..helpers import string_to_point
from ..transactions import TransactionOutput


class CoinbaseTransaction:
    _hex: str = None

    def __init__(self, block_hash: str, address: str, amount: Decimal):
        self.block_hash = block_hash
        self.address = address
        self.amount = amount
        self.outputs = [TransactionOutput(string_to_point(address), amount)]

    async def verify(self):
        from .. import Database
        from ..manager import get_block_reward
        block = await (await Database.get()).get_block(self.block_hash)
        return block['address'] == self.address and self.amount == get_block_reward(block['id'])

    def hex(self):
        if self._hex is not None:
            return self._hex
        hex_inputs = (bytes.fromhex(self.block_hash) + (0).to_bytes(1, ENDIAN)).hex()
        hex_outputs = ''.join(tx_output.tobytes().hex() for tx_output in self.outputs)

        self._hex = ''.join([
            VERSION.to_bytes(1, ENDIAN).hex(),
            (1).to_bytes(1, ENDIAN).hex(),
            hex_inputs,
            (1).to_bytes(1, ENDIAN).hex(),
            hex_outputs,
            (36).to_bytes(1, ENDIAN).hex(),
        ])

        return self._hex
