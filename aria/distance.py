"""VL53L5CX distance frame helpers.

The production v0 bridge should use a compact binary USB CDC frame from the
Pico. During firmware bring-up this module also recognizes simple debug text
that contains 64 integer millimeter values, but text is not the required final
transport.

Binary frames encode each VL53L5CX zone as an unsigned 16-bit millimeter value;
``0`` is reserved as the missing/invalid-distance sentinel and decodes to None.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import struct
from typing import Iterable

from .fusion import TofFrame

MAGIC = b"ARF1"
DISTANCE_PAYLOAD_SIZE = 64 * 2
BINARY_FRAME_SIZE = 4 + 4 + 1 + 1 + 2 + DISTANCE_PAYLOAD_SIZE + 2


@dataclass(frozen=True)
class BinaryTofPacket:
    sequence: int
    status: int
    distances_mm: tuple[int | None, ...]
    checksum: int

    def to_frame(self) -> TofFrame:
        rows = tuple(tuple(self.distances_mm[row * 8 : (row + 1) * 8]) for row in range(8))
        return TofFrame(distances_mm=rows, sequence=self.sequence, status=self.status)


def checksum16(data: bytes) -> int:
    return sum(data) & 0xFFFF


def encode_binary_frame(sequence: int, status: int, distances_mm: Iterable[int | None]) -> bytes:
    values = tuple(0 if value is None else int(value) for value in distances_mm)
    if len(values) != 64:
        raise ValueError("expected exactly 64 distance values")
    header = MAGIC + struct.pack("<IBBH", sequence, status & 0xFF, 0, DISTANCE_PAYLOAD_SIZE)
    payload = struct.pack("<64H", *[max(0, min(65535, value)) for value in values])
    body = header + payload
    return body + struct.pack("<H", checksum16(body))


def parse_binary_frame(data: bytes) -> BinaryTofPacket:
    if len(data) != BINARY_FRAME_SIZE:
        raise ValueError(f"expected {BINARY_FRAME_SIZE} bytes, got {len(data)}")
    if data[:4] != MAGIC:
        raise ValueError("invalid ToF frame magic")
    expected = struct.unpack_from("<H", data, BINARY_FRAME_SIZE - 2)[0]
    actual = checksum16(data[:-2])
    if expected != actual:
        raise ValueError(f"checksum mismatch: expected {expected:#06x}, got {actual:#06x}")
    sequence, status, _reserved, payload_len = struct.unpack_from("<IBBH", data, 4)
    if payload_len != DISTANCE_PAYLOAD_SIZE:
        raise ValueError(f"unexpected payload length: {payload_len}")
    values = struct.unpack_from("<64H", data, 12)
    distances = tuple(None if value == 0 else int(value) for value in values)
    return BinaryTofPacket(sequence=sequence, status=status, distances_mm=distances, checksum=expected)


def parse_text_frame(line: str) -> TofFrame | None:
    """Parse a debug text line containing 64 distance values.

    Accepted examples: ``tof: 1 2 ...`` or comma-separated values. Returns None
    for non-data status lines such as the current firmware's "Scanning...".
    """

    numbers = [int(match) for match in re.findall(r"\b\d+\b", line)]
    if len(numbers) < 64:
        return None
    values = tuple(None if value == 0 else value for value in numbers[-64:])
    rows = tuple(tuple(values[row * 8 : (row + 1) * 8]) for row in range(8))
    return TofFrame(distances_mm=rows)
