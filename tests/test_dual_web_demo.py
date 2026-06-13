"""Tests for dual-camera web demo integration.

These validate the dual-camera CLI, WebDemo dual-mode construction,
and shared state behaviour without requiring real hardware or numpy.
"""

from __future__ import annotations

import pytest

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    HAS_NUMPY = False

import time
from unittest.mock import MagicMock
from aria.camera import CameraFrame
from aria.config import CameraConfig, DetectorConfig, DualCameraConfig, UiConfig
from aria.fusion import BBox, Detection, Region
from aria.quality import CameraQuality
from aria.ui import (
    DemoStatus,
    OverlayRenderer,
    WebDemo,
    _SharedState,
)


def _fake_frame(width=640, height=480):
    class FakeImage:
        def __init__(self, w, h):
            self.shape = (h, w, 3)
    return CameraFrame(
        image=FakeImage(width, height),
        index=1,
        role="right",
        source="/dev/video0",
        timestamp_s=time.monotonic(),
    )


def test_shared_state_dual_jpegs():
    st = _SharedState()
    st.update(
        jpeg={"primary": b"pri", "secondary": b"sec"},
        status=DemoStatus(camera="dual primary=right", dual_mode=True),
    )
    assert st.get_jpeg("primary") == b"pri"
    assert st.get_jpeg("secondary") == b"sec"
    jpeg, status = st.get()
    assert jpeg == b"pri"
    assert status.dual_mode is True


def test_shared_state_backward_compatible_bytes():
    st = _SharedState()
    st.update(jpeg=b"single", status=DemoStatus())
    assert st.get_jpeg("primary") == b"single"
    assert st.get_jpeg("secondary") == b""


def test_webdemo_dual_mode_construction():
    dual = DualCameraConfig(
        cameras={
            "left": CameraConfig(source="/dev/video2"),
            "right": CameraConfig(source="/dev/video0"),
        },
        primary_role="right",
    )
    demo = WebDemo(dual_camera_config=dual, enable_web=False)
    assert demo.dual_mode is True
    assert demo._primary_role == "right"


def test_webdemo_single_mode_construction():
    demo = WebDemo(camera_config=CameraConfig(source="0"), enable_web=False)
    assert demo.dual_mode is False
    assert demo._camera is None


def test_webdemo_switches_to_backup_after_main_quality_is_poor():
    dual = DualCameraConfig(
        cameras={"left": CameraConfig(source="/dev/video2"), "right": CameraConfig(source="/dev/video0")},
        primary_role="right",
    )
    demo = WebDemo(
        dual_camera_config=dual,
        enable_web=False,
        ui_config=UiConfig(backup_switch_after_s=1.0, main_recover_after_s=2.0),
    )
    poor = CameraQuality(status="poor_low_light", reason="dark")
    good = CameraQuality(status="good", mean=80, std=30, under_ratio=0.0, reason="usable")

    demo._update_active_primary({"right": poor, "left": good}, now=10.0)
    assert demo._active_primary_role == "right"
    demo._update_active_primary({"right": poor, "left": good}, now=11.1)
    assert demo._active_primary_role == "left"


def test_webdemo_switches_to_backup_immediately_when_main_frame_failed():
    dual = DualCameraConfig(
        cameras={"left": CameraConfig(source="/dev/video2"), "right": CameraConfig(source="/dev/video0")},
        primary_role="right",
    )
    demo = WebDemo(
        dual_camera_config=dual,
        enable_web=False,
        ui_config=UiConfig(backup_switch_after_s=10.0, main_recover_after_s=2.0),
    )
    failed = CameraQuality(status="failed", reason="missing_frame")
    good = CameraQuality(status="good", mean=80, std=30, under_ratio=0.0, reason="usable")

    changed = demo._update_active_primary({"right": failed, "left": good}, now=10.0)

    assert changed is True
    assert demo._active_primary_role == "left"


def test_webdemo_recovers_main_after_good_quality_hysteresis():
    dual = DualCameraConfig(
        cameras={"left": CameraConfig(source="/dev/video2"), "right": CameraConfig(source="/dev/video0")},
        primary_role="right",
    )
    demo = WebDemo(
        dual_camera_config=dual,
        enable_web=False,
        ui_config=UiConfig(backup_switch_after_s=1.0, main_recover_after_s=2.0),
    )
    demo._active_primary_role = "left"
    good = CameraQuality(status="good", mean=80, std=30, under_ratio=0.0, reason="usable")

    demo._update_active_primary({"right": good, "left": good}, now=20.0)
    assert demo._active_primary_role == "left"
    demo._update_active_primary({"right": good, "left": good}, now=22.1)
    assert demo._active_primary_role == "right"


def test_webdemo_dual_mode_status_fields_without_hardware():
    dual = DualCameraConfig(
        cameras={"left": CameraConfig(source="/dev/video2"), "right": CameraConfig(source="/dev/video0")},
        primary_role="right",
    )
    demo = WebDemo(dual_camera_config=dual, enable_web=False)
    # do not call start() (would try to open real cameras)
    demo._running.set()
    # Manually set multi_camera to a mock to bypass real open()
    mock_left = MagicMock()
    mock_left.status = "open"
    mock_right = MagicMock()
    mock_right.status = "open"
    fake_right = _fake_frame(1280, 720)
    fake_left = _fake_frame(640, 480)
    fake_left.role = "left"
    mock_multi = MagicMock()
    mock_multi.read_frames.return_value = {"right": fake_right, "left": fake_left}
    mock_multi.cameras = {"left": mock_left, "right": mock_right}
    # Default object-detection panel now shows the active physical camera only;
    # raw left/right panels remain separate streams.
    fake_right.image.shape = (720, 1280, 3)
    demo._multi_camera = mock_multi
    # Prevent cv2/numpy from being used by the update path
    import aria.ui as ui_mod
    real_cv2 = ui_mod.cv2
    ui_mod.cv2 = None
    try:
        demo._update()
        status = demo._state.get_status()
        assert status.dual_mode is True
        assert status.primary_role == "right"
        assert status.camera == "active_right (2 cameras)"
        assert "left" in status.cameras
        assert "right" in status.cameras
        assert status.cameras["right"]["status"] == "open"
        assert status.frame_count == 1
    finally:
        ui_mod.cv2 = real_cv2


def test_overlay_renderer_dual_status():
    if not HAS_NUMPY:
        pytest.skip("numpy not available")
    r = OverlayRenderer()
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    status = DemoStatus(camera="dual primary=right", fps=15.0, detection_count=2)
    out = r.render(img, status)
    assert out is not None


def test_run_demo_resolves_hef_path_from_repo_parent(tmp_path, monkeypatch):
    from scripts import run_demo

    repo_root = tmp_path / "aria"
    sibling_proto = tmp_path / "proto" / "prototype" / "models"
    sibling_proto.mkdir(parents=True)
    hef = sibling_proto / "yolov8n_640.hef"
    hef.write_bytes(b"hef")
    repo_root.mkdir()

    monkeypatch.setattr(run_demo, "REPO_ROOT", repo_root)
    monkeypatch.chdir(repo_root)

    resolved = run_demo.resolve_hef_path("proto/prototype/models/yolov8n_640.hef")
    assert resolved == str(hef.resolve())


def test_run_demo_resolves_hef_path_from_current_directory(tmp_path, monkeypatch):
    from scripts import run_demo

    cwd_proto = tmp_path / "proto" / "prototype" / "models"
    cwd_proto.mkdir(parents=True)
    hef = cwd_proto / "yolov8n_640.hef"
    hef.write_bytes(b"hef")

    monkeypatch.setattr(run_demo, "REPO_ROOT", tmp_path / "aria")
    monkeypatch.chdir(tmp_path)

    resolved = run_demo.resolve_hef_path("proto/prototype/models/yolov8n_640.hef")
    assert resolved == str(hef.resolve())


def test_run_demo_dual_camera_flag():
    """CLI --dual-camera flag should build a WebDemo with dual_camera_config set."""
    from unittest.mock import patch
    from scripts.run_demo import build_pipeline
    import argparse
    import os

    ns = argparse.Namespace(
        dual_camera=True,
        primary_role="right",
        web=True,
        qt=False,
        host="0.0.0.0",
        port=8080,
        camera_source="0",
        camera_width=1280,
        camera_height=720,
        camera_fps=30,
        camera_threaded=True,
        tof_port=None,
        tof_baud=115200,
        hef_path=None,
        conf_threshold=0.35,
        detector_input_size=640,
        box_persistence_s=0.45,
        jpeg_quality=60,
        stream_max_width=640,
        raw_stream_fps=10,
        detection_interval_s=0.0,
        web_fps=30,
    )
    # prevent real env from leaking
    with patch.dict(os.environ, {}, clear=False):
        demo = build_pipeline(ns)
    assert demo.dual_mode is True
    assert demo.dual_camera_config is not None
    assert demo.dual_camera_config.primary_role == "right"


def test_webdemo_clears_detection_cache_after_empty_detector_result(monkeypatch):
    np = pytest.importorskip("numpy")

    class FakeDetector:
        def __init__(self):
            self.calls = 0
        def detect(self, frame):
            self.calls += 1
            if self.calls == 1:
                return [Detection(label="person", confidence=0.9, bbox=BBox(10, 10, 30, 30))]
            return []

    demo = WebDemo(
        camera_config=CameraConfig(source="0", threaded=False),
        detector_config=DetectorConfig(model_path="dummy.hef"),
        ui_config=UiConfig(detection_interval_s=0.0, box_persistence_s=0.45),
        enable_web=False,
    )
    demo._detector = FakeDetector()
    frame = CameraFrame(image=np.zeros((80, 120, 3), dtype=np.uint8), index=1)
    camera = MagicMock()
    camera.read_frame.return_value = frame
    camera.status = "open"
    demo._camera = camera
    monkeypatch.setattr(demo._renderer, "render", lambda image, status, detections=None: image)

    demo._update()
    assert demo._last_detections

    demo._update()
    assert demo._last_detections == []
    assert demo._persistence.update([], now=time.monotonic()) == []


def test_webdemo_clears_detection_cache_when_active_primary_changes():
    dual = DualCameraConfig(
        cameras={"left": CameraConfig(source="/dev/video2"), "right": CameraConfig(source="/dev/video0")},
        primary_role="right",
    )
    demo = WebDemo(
        dual_camera_config=dual,
        enable_web=False,
        ui_config=UiConfig(backup_switch_after_s=1.0, main_recover_after_s=2.0),
    )
    demo._last_detections = [Detection(label="person", confidence=0.9, bbox=BBox(10, 10, 30, 30))]
    demo._last_detection_ts = 123.0
    demo._persistence.update(demo._last_detections, now=10.0, image_width=100)
    poor = CameraQuality(status="poor_low_light", reason="dark")
    good = CameraQuality(status="good", mean=80, std=30, under_ratio=0.0, reason="usable")

    changed = demo._update_active_primary({"right": poor, "left": good}, now=10.0)
    assert changed is False
    changed = demo._update_active_primary({"right": poor, "left": good}, now=11.1)

    assert changed is True
    assert demo._active_primary_role == "left"
    assert demo._last_detections == []
    assert demo._last_detection_ts == 0.0
    assert demo._persistence.update([], now=11.2) == []


def test_webdemo_dual_streams_clear_missing_camera_jpeg(monkeypatch):
    np = pytest.importorskip("numpy")
    dual = DualCameraConfig(
        cameras={"left": CameraConfig(source="/dev/video2"), "right": CameraConfig(source="/dev/video0")},
        primary_role="right",
    )
    demo = WebDemo(dual_camera_config=dual, enable_web=False, ui_config=UiConfig(stream_max_width=9999))
    demo._running.set()
    demo._detector = None
    monkeypatch.setattr(demo._renderer, "render", lambda image, status, detections=None: image)
    monkeypatch.setattr("aria.ui._encode_jpeg", lambda image, quality=60: b"jpeg")

    mock_left = MagicMock(status="open")
    mock_right = MagicMock(status="open")
    fake_right = CameraFrame(image=np.zeros((40, 60, 3), dtype=np.uint8), index=1, role="right")
    fake_left = CameraFrame(image=np.zeros((40, 60, 3), dtype=np.uint8), index=1, role="left")
    mock_multi = MagicMock()
    mock_multi.cameras = {"left": mock_left, "right": mock_right}
    mock_multi.read_frames.side_effect = [
        {"right": fake_right, "left": fake_left},
        {"right": fake_right, "left": None},
    ]
    mock_multi.read_foveated_frame.side_effect = [
        (fake_right.image, {"right": {"x_offset": 0, "scale": 1.0, "original_shape": (40, 60)}, "left": {"x_offset": 0, "scale": 1.0, "original_shape": (40, 60)}}),
        (fake_right.image, {"right": {"x_offset": 0, "scale": 1.0, "original_shape": (40, 60)}}),
    ]
    demo._multi_camera = mock_multi

    demo._update()
    assert demo._state.get_jpeg("left") == b"jpeg"

    demo._last_raw_encode_ts = 0.0
    demo._update()
    assert demo._state.get_jpeg("left") == b""
