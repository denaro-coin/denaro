from decimal import Decimal
from io import BytesIO
from typing import List

from fastecdsa import keys
from icecream import ic

from . import TransactionInput, TransactionOutput
from ..exceptions import DoubleSpendException
from ..constants import ENDIAN, SMALLEST, VERSION, MAX_TX_HEX_LENGTH, CURVE
from ..helpers import bytes_to_point, point_to_string

print = ic


class Transaction:
    _hex: str = None
    fees: Decimal = None
    block_hash: str = None

    def __init__(self, inputs: List[TransactionInput], outputs: List[TransactionOutput]):
        assert len(inputs) < 256
        self.inputs = inputs
        self.outputs = outputs

    def hex(self, full: bool = True):
        inputs, outputs = self.inputs, self.outputs
        hex_inputs = ''.join(tx_input.tobytes().hex() for tx_input in inputs)
        hex_outputs = ''.join(tx_output.tobytes().hex() for tx_output in outputs)

        self._hex = ''.join([
            VERSION.to_bytes(1, ENDIAN).hex(),
            len(inputs).to_bytes(1, ENDIAN).hex(),
            hex_inputs,
            (len(outputs)).to_bytes(1, ENDIAN).hex(),
            hex_outputs
        ])

        if not full:
            return self._hex

        self._hex += (0).to_bytes(1, ENDIAN).hex()

        signatures = []
        for tx_input in inputs:
            signed = tx_input.get_signature()
            if signed not in signatures:
                signatures.append(signed)
                self._hex += signed

        return self._hex

    async def verify(self) -> bool:
        if len(self.hex()) > MAX_TX_HEX_LENGTH:
            print(f'too long ({len(self.hex())})')
            return False

        input_amount = 0
        used_inputs = []
        for tx_input in self.inputs:
            input_hash = f"{tx_input.tx_hash}{tx_input.index}"
            if input_hash in used_inputs:
                print('double spend inside same transaction')
                return False
                raise DoubleSpendException
            else:
                used_inputs.append(input_hash)
            if tx_input.signed is None or not await tx_input.verify(self.hex(False)):
                print('not signed')
                return False
            from .. import Database
            tx: Transaction = await tx_input.get_transaction()
            input_output = tx.outputs[tx_input.index]
            input_amount += input_output.amount
            txs: List[Transaction] = await Database.instance.get_transactions_by_contains(tx_input.tx_hash)

            for related_tx in txs:
                if related_tx == self:
                    continue
                for related_input in related_tx.inputs:
                    if related_input.tx_hash == tx_input.tx_hash and related_input.index == tx_input.index:
                        print('double spend')
                        return False

        output_amount = Decimal(0)
        for tx_output in self.outputs:
            if not tx_output.verify():
                return False
            output_amount += tx_output.amount

        if input_amount >= output_amount:
            self.fees = input_amount - output_amount
            assert (self.fees * SMALLEST) % 1 == 0.0
            assert self.fees >= 0
        return input_amount >= output_amount

    def sign(self, private_keys: list = []):
        for private_key in private_keys:
            for input in self.inputs:
                if input.private_key is None and input.transaction is not None:
                    public_key = keys.get_public_key(private_key, CURVE)
                    if public_key == input.transaction.outputs[input.index].public_key:
                        input.private_key = private_key
        for input in self.inputs:
            if input.signed is None and input.private_key is not None:
                input.sign(self.hex(False))
        return self

    @staticmethod
    async def from_hex(hexstring: str, check_signatures: bool = True):
        tx_bytes = BytesIO(bytes.fromhex(hexstring))
        version = int.from_bytes(tx_bytes.read(1), ENDIAN)

        inputs_count = int.from_bytes(tx_bytes.read(1), ENDIAN)

        inputs = []

        for i in range(0, inputs_count):
            tx_hex = tx_bytes.read(32).hex()
            tx_index = int.from_bytes(tx_bytes.read(1), ENDIAN)
            inputs.append(TransactionInput(tx_hex, index=tx_index))

        outputs_count = int.from_bytes(tx_bytes.read(1), ENDIAN)

        outputs = []

        for i in range(0, outputs_count):
            pubkey = tx_bytes.read(64)
            amount_length = int.from_bytes(tx_bytes.read(1), ENDIAN)
            amount = int.from_bytes(tx_bytes.read(amount_length), ENDIAN) / Decimal(SMALLEST)
            outputs.append(TransactionOutput(bytes_to_point(pubkey), amount))

        specifier = int.from_bytes(tx_bytes.read(1), ENDIAN)
        if specifier == 36:
            assert len(inputs) == 1 and len(outputs) == 1
            from . import CoinbaseTransaction
            return CoinbaseTransaction(inputs[0].tx_hash, outputs[0].address, outputs[0].amount)
        else:
            assert specifier == 0

            signatures = []

            while True:
                signed = (int.from_bytes(tx_bytes.read(32), ENDIAN), int.from_bytes(tx_bytes.read(32), ENDIAN))
                if signed[0] == 0:
                    break
                signatures.append(signed)

            if len(signatures) == 1:
                for tx_input in inputs:
                    tx_input.signed = signatures[0]
            elif len(inputs) == len(signatures):
                for i, tx_input in enumerate(inputs):
                    tx_input.signed = signatures[i]
            else:
                if not check_signatures:
                    return Transaction(inputs, outputs)
                index = {}
                for tx_input in inputs:
                    public_key = point_to_string(await tx_input.get_public_key())
                    if public_key not in index.keys():
                        index[public_key] = []
                    index[public_key].append(tx_input)

                for i, signed in enumerate(signatures):
                    for tx_input in index[list(index.keys())[i]]:
                        tx_input.signed = signed

            return Transaction(inputs, outputs)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.hex() == other.hex()
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)
