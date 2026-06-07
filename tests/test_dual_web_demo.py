"""Tests for dual-camera web demo integration.

These validate the dual-camera CLI, WebDemo dual-mode construction,
and shared state behaviour without requiring real hardware or numpy.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from aria.camera import CameraFrame
from aria.config import CameraConfig, DualCameraConfig
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
        assert status.camera == "dual primary=right"
        assert "left" in status.cameras
        assert "right" in status.cameras
        assert status.cameras["right"]["status"] == "open"
        assert status.frame_count == 1
    finally:
        ui_mod.cv2 = real_cv2


def test_overlay_renderer_dual_status():
    r = OverlayRenderer()
    img = "not_an_image"
    status = DemoStatus(camera="dual primary=right", fps=15.0, detection_count=2)
    out = r.render(img, status)
    assert out == img


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
        web_fps=30,
    )
    # prevent real env from leaking
    with patch.dict(os.environ, {}, clear=False):
        demo = build_pipeline(ns)
    assert demo.dual_mode is True
    assert demo.dual_camera_config is not None
    assert demo.dual_camera_config.primary_role == "right"
