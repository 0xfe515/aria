from __future__ import annotations

from pathlib import Path


FIRMWARE = Path(__file__).resolve().parents[1] / "firmware" / "pico_vl53l5cx" / "main.py"


def test_firmware_documents_dfr0440_and_multi_tof_pin_assignments():
    text = FIRMWARE.read_text()
    assert "DFR0440" in text
    assert "HAPTIC_LEFT_PIN = 14" in text
    assert "HAPTIC_RIGHT_PIN = 15" in text
    assert "HAPTIC_SELF_TEST_DUTY" in text
    assert "TOF_SENSORS" in text
    assert "left" in text and "center" in text and "right" in text
    assert "xshut" in text.lower()
    assert "0x2A" in text or "0x2a" in text
    assert "0x2B" in text or "0x2b" in text


def test_firmware_self_tests_haptics_left_right_then_both_after_tof_ready():
    text = FIRMWARE.read_text()
    assert "def haptic_self_test" in text
    assert "successful ToF discovery" in text
    assert "(HAPTIC_SELF_TEST_DUTY, 0)" in text
    assert "(0, HAPTIC_SELF_TEST_DUTY)" in text
    assert "(HAPTIC_SELF_TEST_DUTY, HAPTIC_SELF_TEST_DUTY)" in text
    assert "sensors = discover_tof_sensors()\n            blink(3, 80)\n            haptic_self_test()" in text


def test_firmware_has_single_and_three_sensor_paths_for_same_default_address():
    text = FIRMWARE.read_text()
    assert "discover_tof_sensors" in text
    assert "init_three_sensors" in text
    assert "init_single_sensor" in text
    assert "set_sensor_address" in text
    assert "0x29" in text


def test_firmware_accepts_bounded_positive_distances_up_to_4m():
    text = FIRMWARE.read_text()
    assert "VL53L5CX_MAX_RANGE_MM = 4000" in text
    assert "0 < distance <= VL53L5CX_MAX_RANGE_MM" in text
    assert "target_status in VALID_STATUSES" not in text
