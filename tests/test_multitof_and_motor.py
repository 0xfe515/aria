from __future__ import annotations

from aria.config import HapticConfig, TofConfig
from aria.distance import (
    MULTI_BINARY_FRAME_SIZE,
    encode_binary_frame,
    encode_multi_binary_frame,
    parse_any_binary_frame,
    parse_multi_binary_frame,
)
from aria.fusion import Detection, Region, TofFrame, TofFrameSet, fuse_detection


def _flat(value: int):
    return tuple(value for _ in range(64))


def _grid(value: int):
    return tuple(tuple(value for _ in range(8)) for _ in range(8))


def test_multi_tof_round_trip_preserves_left_center_right_roles():
    packet = encode_multi_binary_frame(
        sequence=7,
        status=0,
        sensors={"left": _flat(1100), "center": _flat(700), "right": _flat(2100)},
    )

    assert len(packet) == MULTI_BINARY_FRAME_SIZE
    parsed = parse_multi_binary_frame(packet)

    assert parsed.sequence == 7
    assert parsed.sensor_count == 3
    assert parsed.sensors["left"].distances_mm[0] == 1100
    assert parsed.sensors["center"].distances_mm[0] == 700
    assert parsed.sensors["right"].distances_mm[0] == 2100


def test_parse_any_binary_frame_accepts_legacy_single_sensor_packet():
    legacy = encode_binary_frame(sequence=3, status=0, distances_mm=_flat(900))
    parsed = parse_any_binary_frame(legacy)

    assert parsed.sequence == 3
    assert parsed.sensor_count == 1
    assert set(parsed.sensors) == {"center"}


def test_tof_frame_set_uses_center_sensor_for_single_tof_and_role_sensors_for_three_tof():
    single = TofFrameSet({"center": TofFrame(_grid(1000))})
    assert single.distance_for_region(Region.LEFT) == 1000
    assert single.distance_for_region(Region.CENTER) == 1000
    assert single.distance_for_region(Region.RIGHT) == 1000

    triple = TofFrameSet(
        {
            "left": TofFrame(_grid(1200)),
            "center": TofFrame(_grid(600)),
            "right": TofFrame(_grid(2200)),
        }
    )
    assert triple.distance_for_region(Region.LEFT) == 1200
    assert triple.distance_for_region(Region.CENTER) == 600
    assert triple.distance_for_region(Region.RIGHT) == 2200


def test_fuse_detection_accepts_tof_frame_set_for_region_specific_distances():
    tof = TofFrameSet(
        {
            "left": TofFrame(_grid(1200)),
            "center": TofFrame(_grid(600)),
            "right": TofFrame(_grid(2200)),
        }
    )

    left_det = Detection(label="person", confidence=0.9, bbox=(10, 10, 40, 40))
    center_det = Detection(label="person", confidence=0.9, bbox=(300, 10, 340, 40))
    right_det = Detection(label="person", confidence=0.9, bbox=(590, 10, 630, 40))

    assert fuse_detection(left_det, (480, 640, 3), tof).distance_mm == 1200
    assert fuse_detection(center_det, (480, 640, 3), tof).distance_mm == 600
    assert fuse_detection(right_det, (480, 640, 3), tof).distance_mm == 2200


def test_tof_config_defaults_support_one_or_three_sensors_with_xshut_pins():
    cfg = TofConfig()
    assert cfg.expected_sensors == ("center",)
    assert cfg.xshut_pins == {"left": 10, "center": 11, "right": 12}
    assert cfg.addresses == {"left": 0x2A, "center": 0x29, "right": 0x2B}


def test_haptic_config_defaults_assign_two_dfr0440_motors_to_pwm_pins():
    cfg = HapticConfig()
    assert cfg.enabled is True
    assert cfg.left_pin == 14
    assert cfg.right_pin == 15
    assert cfg.pwm_hz == 200
    assert cfg.active_high is True
