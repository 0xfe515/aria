import importlib.util
import sys
from pathlib import Path


def load_verify_dual_camera():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_dual_camera.py"
    spec = importlib.util.spec_from_file_location("verify_dual_camera", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_normalize_device_accepts_numeric_and_paths():
    module = load_verify_dual_camera()

    assert module.normalize_device("0") == 0
    assert module.normalize_device("/dev/video2") == "/dev/video2"


def test_shape_to_list_handles_tuple_none_and_missing_shape():
    module = load_verify_dual_camera()

    assert module.shape_to_list((480, 640, 3)) == [480, 640, 3]
    assert module.shape_to_list(None) is None
    assert module.shape_to_list(object()) is None


def test_camera_stats_records_fps_shape_and_failures():
    module = load_verify_dual_camera()
    stats = module.CameraStats(role="left", device="/dev/video2")

    stats.record_frame((480, 640, 3), timestamp_s=10.0)
    stats.record_frame((480, 640, 3), timestamp_s=10.5)
    stats.record_failure()

    summary = stats.summary(start_s=10.0, end_s=11.0)
    assert summary == {
        "role": "left",
        "device": "/dev/video2",
        "opened": True,
        "frames": 2,
        "failures": 1,
        "shape": [480, 640, 3],
        "fps": 2.0,
        "first_timestamp_s": 10.0,
        "last_timestamp_s": 10.5,
    }


def test_timestamp_skew_uses_latest_frame_timestamps():
    module = load_verify_dual_camera()
    left = module.CameraStats(role="left", device="/dev/video2")
    right = module.CameraStats(role="right", device="/dev/video0")
    left.record_frame((480, 640, 3), timestamp_s=100.25)
    right.record_frame((720, 1280, 3), timestamp_s=100.10)

    assert module.latest_timestamp_skew_ms({"left": left, "right": right}) == 150.0


def test_timestamp_skew_none_when_any_camera_has_no_frame():
    module = load_verify_dual_camera()
    left = module.CameraStats(role="left", device="/dev/video2")
    right = module.CameraStats(role="right", device="/dev/video0")
    left.record_frame((480, 640, 3), timestamp_s=100.25)

    assert module.latest_timestamp_skew_ms({"left": left, "right": right}) is None
