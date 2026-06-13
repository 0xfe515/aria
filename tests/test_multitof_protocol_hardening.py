from __future__ import annotations

import pytest

from aria.distance import MULTI_MAGIC, checksum16, encode_multi_binary_frame, parse_multi_binary_frame
from aria.ui import TofSerialReader


def test_multi_tof_rejects_unknown_role_id():
    payload = bytes([9, 0, 0, 0]) + (100).to_bytes(2, "little") * 64
    body = MULTI_MAGIC + (1).to_bytes(4, "little") + bytes([0, 1]) + len(payload).to_bytes(2, "little") + payload
    packet = body + checksum16(body).to_bytes(2, "little")

    with pytest.raises(ValueError, match="unknown ToF role id"):
        parse_multi_binary_frame(packet)


def test_multi_tof_rejects_partial_two_sensor_layout():
    packet = encode_multi_binary_frame(1, 0, {"left": [100] * 64, "center": [200] * 64})

    with pytest.raises(ValueError, match="expected either one center ToF or three"):
        parse_multi_binary_frame(packet)


def test_tof_serial_reader_handles_zero_sensor_error_frame_without_crashing():
    payload = b""
    body = MULTI_MAGIC + (5).to_bytes(4, "little") + bytes([1, 0]) + len(payload).to_bytes(2, "little") + payload
    packet = body + checksum16(body).to_bytes(2, "little")

    parsed = parse_multi_binary_frame(packet)
    assert parsed.sensor_count == 0

    reader = TofSerialReader("dummy")
    assert reader._frame_size(bytearray(packet)) == len(packet)
