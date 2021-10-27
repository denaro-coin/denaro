import hashlib
import json
import os
from math import ceil
from datetime import datetime, timezone
from typing import Union

from fastecdsa.point import Point

from .constants import ENDIAN, CURVE


def get_json(obj):
  return json.loads(
    json.dumps(obj, default=lambda o: getattr(o, 'as_dict', getattr(o, '__dict__', str(o))))
  )


def timestamp():
    return int(datetime.now(timezone.utc).replace(tzinfo=timezone.utc).timestamp())


def sha256(message: Union[str, bytes]):
    if isinstance(message, bytes):
        return hashlib.sha256(message).hexdigest()
    try:
        return hashlib.sha256(bytes.fromhex(message)).hexdigest()
    except ValueError:
        return hashlib.sha256(bytes(message, 'utf-8')).hexdigest()


def random_hex():
    return os.urandom(32).hex()


def byte_length(i: int):
    return ceil(i.bit_length() / 8.0)


def point_to_bytes(point: Point) -> bytes:
    return point.x.to_bytes(32, byteorder=ENDIAN) + point.y.to_bytes(32, byteorder=ENDIAN)


def bytes_to_point(points_bytes: bytes) -> Point:
    x, y = int.from_bytes(points_bytes[:32], ENDIAN), int.from_bytes(points_bytes[32:], ENDIAN)
    return Point(x, y, CURVE)


def point_to_string(point: Point) -> str:
    point_bytes = point_to_bytes(point)
    #return (base64.urlsafe_b64encode(point_bytes)).decode("utf-8")
    return point_bytes.hex()
    return str(int.from_bytes(point_bytes, ENDIAN))

    #print(int.from_bytes(point_bytes, ENDIAN))
    #print(hex(int.from_bytes(point_bytes, ENDIAN)))
    #print(point_bytes.hex())

    # hex dei bytes
    #return point_bytes.hex()

    # sha256 dei bytes (hex)
    #return hashlib.sha256(point_bytes).hexdigest()

    # base64 dello sha dei bytes
    #return (base64.urlsafe_b64encode(hashlib.sha256(point_bytes).digest())).decode("utf-8")

    # sha del base64 dei bytes
    #return sha256((base64.urlsafe_b64encode(point_bytes).decode("utf-8") ))

    # base64 dei bytes
    #return (base64.urlsafe_b64encode(point_bytes)).decode("utf-8")


def string_to_point(string: str) -> Point:
    #points_bytes = int(string).to_bytes(64, ENDIAN)
    points_bytes = bytes.fromhex(string)
    return bytes_to_point(points_bytes)


