from decimal import Decimal
from typing import Tuple

from fastecdsa import ecdsa
from fastecdsa.point import Point

from ..constants import CURVE, ENDIAN, SMALLEST
from ..helpers import point_to_string, string_to_point


class TransactionInput:
    public_key = None

    signed: Tuple[int, int] = None
    amount: Decimal = None

    def __init__(self, input_tx_hash: str, index: int, private_key: int = None, transaction=None, amount: Decimal = None, public_key: Point = None):
        self.tx_hash = input_tx_hash
        self.index = index
        self.private_key = private_key
        self.transaction = transaction
        self.transaction_info = None
        self.amount = amount
        self.public_key = public_key
        if transaction is not None and amount is None:
            self.get_related_output()

    async def get_transaction(self):
        if self.transaction is None:
            from .. import Database
            self.transaction = await Database.instance.get_transaction(self.tx_hash, check_signatures=False)
            assert self.transaction is not None
        return self.transaction

    async def get_transaction_info(self):
        if self.transaction_info is None:
            from .. import Database
            self.transaction_info = await Database.instance.get_transaction_info(self.tx_hash)
        assert self.transaction_info is not None
        return self.transaction_info

    async def get_related_output(self):
        tx = await self.get_transaction()
        related_output = tx.outputs[self.index]
        self.amount = related_output.amount
        return related_output

    async def get_related_output_info(self):
        tx = await self.get_transaction_info()
        related_output = {'address': tx['outputs_addresses'][self.index], 'amount': Decimal(tx['outputs_amounts'][self.index]) / SMALLEST}
        self.amount = related_output['amount']
        return related_output

    async def get_amount(self):
        if self.amount is None:
            if self.transaction is not None:
                return self.transaction.outputs[self.index].amount
            else:
                await self.get_related_output_info()
        return self.amount

    async def get_address(self):
        if self.transaction is not None:
            return (await self.get_related_output()).address
        return (await self.get_related_output_info())['address']

    def sign(self, tx_hex: str, private_key: int = None):
        private_key = private_key if private_key is not None else self.private_key
        self.signed = ecdsa.sign(bytes.fromhex(tx_hex), private_key)

    async def get_public_key(self):
        return self.public_key or string_to_point(await self.get_address())

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
            ecdsa.verify(self.signed, bytes.fromhex(input_tx), public_key, CURVE) or \
            ecdsa.verify(self.signed, input_tx, public_key, CURVE)

    @property
    def as_dict(self):
        self_dict = vars(self).copy()
        self_dict['signed'] = self_dict['signed'] is not None
        if 'public_key' in self_dict: self_dict['public_key'] = point_to_string(self_dict['public_key'])
        if 'transaction' in self_dict: del self_dict['transaction']
        if 'private_key' in self_dict: del self_dict['private_key']
        return self_dict

    def __eq__(self, other):
        assert isinstance(other, self.__class__)
        return (self.tx_hash, self.index) == (other.tx_hash, other.index)
