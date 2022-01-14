from decimal import Decimal
from typing import Tuple

from fastecdsa import ecdsa

from ..constants import CURVE, ENDIAN
from ..helpers import point_to_string


class TransactionInput:
    public_key = None

    signed: Tuple[int, int] = None
    amount: Decimal = None

    def __init__(self, input_tx_hash: str, index: int, private_key: int = None, transaction=None, amount: Decimal = None):
        self.tx_hash = input_tx_hash
        self.index = index
        self.private_key = private_key
        self.transaction = transaction
        self.amount = amount
        if transaction is not None and amount is None:
            self.get_related_output()

    async def get_transaction(self):
        if self.transaction is None:
            from .. import Database
            tx = await Database.instance.get_transaction(self.tx_hash, check_signatures=False)
            assert tx is not None
            self.transaction = tx
        return self.transaction

    async def get_related_output(self):
        tx = await self.get_transaction()
        related_output = tx.outputs[self.index]
        self.amount = related_output.amount
        return related_output

    def sign(self, tx_hex: str, private_key: int = None):
        private_key = private_key if private_key is not None else self.private_key
        self.signed = ecdsa.sign(bytes.fromhex(tx_hex),      private_key)

    async def get_public_key(self):
        return (await self.get_related_output()).public_key

    def tobytes(self):
        return bytes.fromhex(self.tx_hash) + self.index.to_bytes(1, ENDIAN)

    def get_signature(self):
        return self.signed[0].to_bytes(32, ENDIAN).hex() + self.signed[1].to_bytes(32, ENDIAN).hex()

    async def verify(self, input_tx) -> bool:
        try:
            public_key = await self.get_public_key()
        except AssertionError:
            return False
        # print('verifying with', point_to_string(public_key))

        return \
            ecdsa.verify(self.signed, input_tx, public_key, CURVE) or \
            ecdsa.verify(self.signed, bytes.fromhex(input_tx), public_key, CURVE)

    @property
    def as_dict(self):
        self_dict = vars(self).copy()
        self_dict['signed'] = self_dict['signed'] is not None
        if 'public_key' in self_dict: self_dict['public_key'] = point_to_string(self_dict['public_key'])
        if 'transaction' in self_dict: del self_dict['transaction']
        if 'private_key' in self_dict: del self_dict['private_key']
        return self_dict
