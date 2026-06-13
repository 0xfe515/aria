"""VL53L5CX distance frame helpers.

The production bridge uses compact binary USB CDC frames from the Pico.
Legacy ``ARF1`` packets carry one 8x8 VL53L5CX frame and map to the center
region. New ``ARF2`` packets carry one to three explicitly-role-tagged sensors
(left/center/right) so the same Pi-side code can run with either one ToF or the
planned three-ToF layout.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import struct
from typing import Iterable

from .fusion import TofFrame

MAGIC = b"ARF1"
MULTI_MAGIC = b"ARF2"
DISTANCE_PAYLOAD_SIZE = 64 * 2
BINARY_FRAME_SIZE = 4 + 4 + 1 + 1 + 2 + DISTANCE_PAYLOAD_SIZE + 2
SENSOR_BLOCK_SIZE = 1 + 1 + 2 + DISTANCE_PAYLOAD_SIZE
MULTI_DISTANCE_PAYLOAD_SIZE = 3 * SENSOR_BLOCK_SIZE
MULTI_BINARY_FRAME_SIZE = 4 + 4 + 1 + 1 + 2 + MULTI_DISTANCE_PAYLOAD_SIZE + 2

ROLE_TO_ID = {"left": 1, "center": 2, "right": 3}
ID_TO_ROLE = {value: key for key, value in ROLE_TO_ID.items()}


@dataclass(frozen=True)
class BinaryTofPacket:
    sequence: int
    status: int
    distances_mm: tuple[int | None, ...]
    checksum: int

    def to_frame(self) -> TofFrame:
        rows = tuple(tuple(self.distances_mm[row * 8 : (row + 1) * 8]) for row in range(8))
        return TofFrame(distances_mm=rows, sequence=self.sequence, status=self.status)


@dataclass(frozen=True)
class MultiTofPacket:
    sequence: int
    status: int
    sensors: dict[str, BinaryTofPacket]
    checksum: int

    @property
    def sensor_count(self) -> int:
        return len(self.sensors)

    def to_frame_set(self):
        from .fusion import TofFrameSet

        return TofFrameSet({role: packet.to_frame() for role, packet in self.sensors.items()})


def checksum16(data: bytes) -> int:
    return sum(data) & 0xFFFF


def _distance_payload(distances_mm: Iterable[int | None]) -> bytes:
    values = tuple(0 if value is None else int(value) for value in distances_mm)
    if len(values) != 64:
        raise ValueError("expected exactly 64 distance values")
    return struct.pack("<64H", *[max(0, min(65535, value)) for value in values])


def encode_binary_frame(sequence: int, status: int, distances_mm: Iterable[int | None]) -> bytes:
    values = tuple(0 if value is None else int(value) for value in distances_mm)
    if len(values) != 64:
        raise ValueError("expected exactly 64 distance values")
    header = MAGIC + struct.pack("<IBBH", sequence, status & 0xFF, 0, DISTANCE_PAYLOAD_SIZE)
    payload = struct.pack("<64H", *[max(0, min(65535, value)) for value in values])
    body = header + payload
    return body + struct.pack("<H", checksum16(body))


def encode_multi_binary_frame(
    sequence: int,
    status: int,
    sensors: dict[str, Iterable[int | None]],
    sensor_statuses: dict[str, int] | None = None,
) -> bytes:
    """Encode one to three VL53L5CX sensors into an ARF2 packet."""

    sensor_statuses = sensor_statuses or {}
    blocks = bytearray()
    roles = [role for role in ("left", "center", "right") if role in sensors]
    if not roles:
        raise ValueError("expected at least one sensor")
    for role in roles:
        blocks.extend(struct.pack("<BBH", ROLE_TO_ID[role], sensor_statuses.get(role, 0) & 0xFF, 0))
        blocks.extend(_distance_payload(sensors[role]))
    header = MULTI_MAGIC + struct.pack("<IBBH", sequence & 0xFFFFFFFF, status & 0xFF, len(roles), len(blocks))
    body = header + bytes(blocks)
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


def parse_multi_binary_frame(data: bytes) -> MultiTofPacket:
    if len(data) < 14:
        raise ValueError(f"expected at least 14 bytes, got {len(data)}")
    if data[:4] != MULTI_MAGIC:
        raise ValueError("invalid multi-ToF frame magic")
    sequence, status, sensor_count, payload_len = struct.unpack_from("<IBBH", data, 4)
    expected_size = 4 + 4 + 1 + 1 + 2 + payload_len + 2
    if len(data) != expected_size:
        raise ValueError(f"expected {expected_size} bytes, got {len(data)}")
    expected = struct.unpack_from("<H", data, expected_size - 2)[0]
    actual = checksum16(data[:-2])
    if expected != actual:
        raise ValueError(f"checksum mismatch: expected {expected:#06x}, got {actual:#06x}")
    if payload_len % SENSOR_BLOCK_SIZE != 0:
        raise ValueError(f"unexpected multi-ToF payload length: {payload_len}")

    sensors: dict[str, BinaryTofPacket] = {}
    offset = 12
    for _ in range(payload_len // SENSOR_BLOCK_SIZE):
        role_id, sensor_status, _reserved = struct.unpack_from("<BBH", data, offset)
        offset += 4
        values = struct.unpack_from("<64H", data, offset)
        offset += DISTANCE_PAYLOAD_SIZE
        role = ID_TO_ROLE.get(role_id)
        if role is None:
            raise ValueError(f"unknown ToF role id: {role_id}")
        if role in sensors:
            raise ValueError(f"duplicate ToF role: {role}")
        distances = tuple(None if value == 0 else int(value) for value in values)
        sensors[role] = BinaryTofPacket(sequence=sequence, status=sensor_status, distances_mm=distances, checksum=expected)
    if sensor_count != len(sensors):
        raise ValueError(f"sensor count mismatch: header {sensor_count}, payload {len(sensors)}")
    roles = set(sensors)
    if roles and roles not in ({"center"}, {"left", "center", "right"}):
        raise ValueError("expected either one center ToF or three left/center/right ToFs")
    return MultiTofPacket(sequence=sequence, status=status, sensors=sensors, checksum=expected)


def parse_any_binary_frame(data: bytes) -> MultiTofPacket:
    """Parse either legacy ARF1 single-center packets or ARF2 multi-ToF packets."""

    if data.startswith(MAGIC):
        packet = parse_binary_frame(data)
        return MultiTofPacket(sequence=packet.sequence, status=packet.status, sensors={"center": packet}, checksum=packet.checksum)
    return parse_multi_binary_frame(data)


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
