import pytest

from aria.distance import BINARY_FRAME_SIZE, encode_binary_frame, parse_binary_frame, parse_text_frame


def test_binary_tof_round_trip():
    values = list(range(1, 65))
    packet = encode_binary_frame(sequence=42, status=3, distances_mm=values)
    assert len(packet) == BINARY_FRAME_SIZE
    parsed = parse_binary_frame(packet)
    assert parsed.sequence == 42
    assert parsed.status == 3
    assert parsed.distances_mm == tuple(values)
    frame = parsed.to_frame()
    assert frame.sequence == 42
    assert frame.distances_mm[0][0] == 1
    assert frame.distances_mm[7][7] == 64


def test_binary_tof_keeps_documented_4m_range_and_drops_beyond_range():
    values = [3999, 4000, 4001, 0] + [100] * 60
    packet = encode_binary_frame(sequence=7, status=0, distances_mm=values)

    parsed = parse_binary_frame(packet)

    assert parsed.distances_mm[:4] == (3999, 4000, None, None)


def test_binary_tof_rejects_bad_checksum():
    packet = bytearray(encode_binary_frame(1, 0, [100] * 64))
    packet[20] ^= 0x01
    with pytest.raises(ValueError, match="checksum mismatch"):
        parse_binary_frame(bytes(packet))


def test_binary_tof_rejects_unexpected_payload_length():
    packet = bytearray(encode_binary_frame(1, 0, [100] * 64))
    packet[10] = 0
    checksum = sum(packet[:-2]) & 0xFFFF
    packet[-2:] = checksum.to_bytes(2, "little")
    with pytest.raises(ValueError, match="unexpected payload length"):
        parse_binary_frame(bytes(packet))


def test_text_parser_ignores_status_lines_and_accepts_64_values():
    assert parse_text_frame("Scanning...") is None
    frame = parse_text_frame("tof: " + ",".join(str(100 + i) for i in range(64)))
    assert frame is not None
    assert frame.distances_mm[0][0] == 100
    assert frame.distances_mm[7][7] == 163


def test_text_parser_uses_same_4m_distance_range():
    values = [4000, 4001, 0] + [200] * 61
    frame = parse_text_frame("tof: " + ",".join(str(value) for value in values))

    assert frame is not None
    assert frame.distances_mm[0][:3] == (4000, None, None)
