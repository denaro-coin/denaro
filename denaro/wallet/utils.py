from decimal import Decimal

from fastecdsa import keys

from denaro import Database
from denaro.constants import CURVE
from denaro.helpers import point_to_string
from denaro.transactions import Transaction, TransactionOutput


async def create_transaction(private_keys, receiving_address, amount, message: bytes = None, send_back_address=None):
    denaro_database: Database = await Database.get()
    amount = Decimal(amount)
    inputs = []
    for private_key in private_keys:
        address = point_to_string(keys.get_public_key(private_key, CURVE))
        if send_back_address is None:
            send_back_address = address
        inputs.extend(await denaro_database.get_spendable_outputs(address, check_pending_txs=True))
        if sum(input.amount for input in inputs) >= amount:
            break
    if not inputs:
        raise Exception('No spendable outputs')

    if sum(input.amount for input in inputs) < amount:
        raise Exception(f"Error: You don\'t have enough funds")

    most_amount = sorted(inputs, key=lambda item: item.amount, reverse=True)

    transaction_inputs = []

    for i, tx_input in enumerate(most_amount):
        transaction_inputs.append(tx_input)
        transaction_amount = sum(input.amount for input in transaction_inputs)
        if transaction_amount >= amount:
            break

    transaction_amount = sum(input.amount for input in transaction_inputs)

    transaction = Transaction(transaction_inputs, [TransactionOutput(receiving_address, amount=amount)], message)
    if transaction_amount > amount:
        transaction.outputs.append(TransactionOutput(address, transaction_amount - amount))

    transaction.sign(private_keys)

    return transaction


def string_to_bytes(string: str) -> bytes:
    if string is None:
        return None
    try:
        return bytes.fromhex(string)
    except ValueError:
        return string.encode('utf-8')
