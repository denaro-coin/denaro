import hashlib
import json
import logging
import sys
from math import ceil
from datetime import datetime, timezone
from typing import Union

from fastecdsa.point import Point
from icecream import ic

from .constants import ENDIAN, CURVE

_print = print

logging.basicConfig(level=logging.INFO if '--nologs' not in sys.argv else logging.WARNING)


def log(s):
    logging.getLogger('denaro').info(s)


ic.configureOutput(outputFunction=log)


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


def byte_length(i: int):
    return ceil(i.bit_length() / 8.0)


def point_to_bytes(point: Point) -> bytes:
    return point.x.to_bytes(32, byteorder=ENDIAN) + point.y.to_bytes(32, byteorder=ENDIAN)


def bytes_to_point(points_bytes: bytes) -> Point:
    x, y = int.from_bytes(points_bytes[:32], ENDIAN), int.from_bytes(points_bytes[32:], ENDIAN)
    return Point(x, y, CURVE)


def point_to_string(point: Point) -> str:
    point_bytes = point_to_bytes(point)
    return point_bytes.hex()


def string_to_point(string: str) -> Point:
    points_bytes = bytes.fromhex(string)
    return bytes_to_point(points_bytes)


