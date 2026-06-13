from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aria.camera import CameraFrame
from aria.config import CameraConfig, DualCameraConfig, UiConfig
from aria.fusion import BBox, Detection
from aria.ui import WebDemo


def test_dual_demo_combined_stream_shows_active_camera_only_not_foveated_half_mix(monkeypatch):
    np = pytest.importorskip("numpy")
    dual = DualCameraConfig(
        cameras={"left": CameraConfig(source="/dev/video2"), "right": CameraConfig(source="/dev/video0")},
        primary_role="right",
    )
    demo = WebDemo(dual_camera_config=dual, enable_web=False, ui_config=UiConfig(stream_max_width=9999, detection_interval_s=0.0))
    demo._running.set()

    right_img = np.full((40, 60, 3), 20, dtype=np.uint8)
    left_img = np.full((40, 60, 3), 200, dtype=np.uint8)
    fake_right = CameraFrame(image=right_img, index=1, role="right")
    fake_left = CameraFrame(image=left_img, index=1, role="left")
    mock_multi = MagicMock()
    mock_multi.cameras = {"left": MagicMock(status="open"), "right": MagicMock(status="open")}
    mock_multi.read_frames.return_value = {"right": fake_right, "left": fake_left}
    demo._multi_camera = mock_multi
    demo._detector = MagicMock()
    demo._detector.detect.return_value = [Detection(label="person", confidence=0.9, bbox=BBox(5, 5, 20, 20))]

    rendered = []
    monkeypatch.setattr(demo._renderer, "render", lambda image, status, detections=None: rendered.append((image.copy(), status.active_primary_role, detections)) or image)
    monkeypatch.setattr("aria.ui._encode_jpeg", lambda image, quality=60: b"jpeg")

    demo._update()

    assert rendered
    image, role, detections = rendered[0]
    assert role == "right"
    assert image.shape == right_img.shape
    assert int(image.mean()) == 20
    assert detections
    mock_multi.read_foveated_frame.assert_not_called()


def test_dual_demo_active_view_switches_to_backup_camera_after_failover(monkeypatch):
    np = pytest.importorskip("numpy")
    dual = DualCameraConfig(
        cameras={"left": CameraConfig(source="/dev/video2"), "right": CameraConfig(source="/dev/video0")},
        primary_role="right",
    )
    demo = WebDemo(
        dual_camera_config=dual,
        enable_web=False,
        ui_config=UiConfig(stream_max_width=9999, detection_interval_s=0.0, backup_switch_after_s=0.0),
    )
    demo._running.set()

    right_img = np.zeros((40, 60, 3), dtype=np.uint8)
    left_img = np.full((40, 60, 3), 120, dtype=np.uint8)
    left_img[:, ::2] = 60
    left_img[::2, :] = 220
    fake_right = CameraFrame(image=right_img, index=1, role="right")
    fake_left = CameraFrame(image=left_img, index=1, role="left")
    mock_multi = MagicMock()
    mock_multi.cameras = {"left": MagicMock(status="open"), "right": MagicMock(status="open")}
    mock_multi.read_frames.return_value = {"right": fake_right, "left": fake_left}
    demo._multi_camera = mock_multi
    demo._detector = MagicMock()
    demo._detector.detect.return_value = [Detection(label="person", confidence=0.9, bbox=BBox(5, 5, 20, 20))]

    rendered = []
    monkeypatch.setattr(demo._renderer, "render", lambda image, status, detections=None: rendered.append((image.copy(), status.active_primary_role, status.backup_active)) or image)
    monkeypatch.setattr("aria.ui._encode_jpeg", lambda image, quality=60: b"jpeg")

    demo._update()

    image, role, backup_active = rendered[0]
    assert role == "left"
    assert backup_active is True
    assert image.shape == left_img.shape
    assert int(image.mean()) == int(left_img.mean())
