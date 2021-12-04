from decimal import Decimal

from fastecdsa.point import Point

from ..constants import ENDIAN, SMALLEST, CURVE
from ..helpers import byte_length, point_to_bytes, point_to_string


class TransactionOutput:
    def __init__(self, public_key: Point, amount: Decimal):
        self.public_key = public_key
        self.address = point_to_string(public_key)
        assert (amount * SMALLEST) % 1 == 0.0
        self.amount = amount

    def tobytes(self):
        amount = int(self.amount * SMALLEST)
        count = byte_length(amount)
        return point_to_bytes(self.public_key) + count.to_bytes(1, ENDIAN) + amount.to_bytes(count, ENDIAN)

    def verify(self):
        return self.amount > 0 and CURVE.is_point_on_curve(self.public_key)

    @property
    def as_dict(self):
        res = vars(self).copy()
        if 'public_key' in res: del res['public_key']
        return res
