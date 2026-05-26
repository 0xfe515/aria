from aria.camera import Camera, list_video_nodes
from aria.config import CameraConfig


def test_camera_config_normalizes_numeric_source():
    assert CameraConfig(source="0").normalized_source() == 0
    assert CameraConfig(source="/dev/video0").normalized_source() == "/dev/video0"


def test_list_video_nodes_with_temp_dev(tmp_path):
    (tmp_path / "video2").touch()
    (tmp_path / "video0").touch()
    (tmp_path / "notvideo").touch()
    assert list_video_nodes(tmp_path) == [str(tmp_path / "video0"), str(tmp_path / "video2")]


def test_camera_reports_opencv_unavailable_when_import_fails(monkeypatch):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("no cv2")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    camera = Camera(CameraConfig())
    assert camera.open() is False
    assert camera.status.startswith("opencv_unavailable")
