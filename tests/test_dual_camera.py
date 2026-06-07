from aria.camera import CameraFrame, MultiCamera
from aria.config import CameraConfig, DualCameraConfig


class FakeCamera:
    def __init__(self, config):
        self.config = config
        self.status = "not_opened"
        self.opened = False
        self.released = False
        self.reads = 0

    def open(self):
        self.opened = self.config.source != "missing"
        self.status = "open" if self.opened else "open_failed"
        return self.opened

    def read_frame(self):
        if not self.opened:
            return None
        self.reads += 1
        return CameraFrame(image={"source": self.config.source}, index=self.reads)

    def release(self):
        self.released = True
        self.status = "released"


def test_dual_camera_config_uses_left_and_right_environment(monkeypatch):
    monkeypatch.setenv("ARIA_LEFT_CAMERA_SOURCE", "/dev/video2")
    monkeypatch.setenv("ARIA_RIGHT_CAMERA_SOURCE", "/dev/video0")
    monkeypatch.setenv("ARIA_LEFT_CAMERA_WIDTH", "640")
    monkeypatch.setenv("ARIA_LEFT_CAMERA_HEIGHT", "480")
    monkeypatch.setenv("ARIA_RIGHT_CAMERA_WIDTH", "1280")
    monkeypatch.setenv("ARIA_RIGHT_CAMERA_HEIGHT", "720")
    monkeypatch.setenv("ARIA_PRIMARY_CAMERA", "right")

    config = DualCameraConfig.from_env()

    assert config.primary_role == "right"
    assert config.cameras["left"].source == "/dev/video2"
    assert config.cameras["left"].width == 640
    assert config.cameras["left"].height == 480
    assert config.cameras["right"].source == "/dev/video0"
    assert config.cameras["right"].width == 1280
    assert config.cameras["right"].height == 720


def test_dual_camera_config_defaults_match_aria_core_mapping(monkeypatch):
    for name in [
        "ARIA_LEFT_CAMERA_SOURCE",
        "ARIA_RIGHT_CAMERA_SOURCE",
        "ARIA_LEFT_CAMERA_WIDTH",
        "ARIA_LEFT_CAMERA_HEIGHT",
        "ARIA_RIGHT_CAMERA_WIDTH",
        "ARIA_RIGHT_CAMERA_HEIGHT",
        "ARIA_PRIMARY_CAMERA",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = DualCameraConfig.from_env()

    assert config.primary_role == "right"
    assert config.cameras["left"].source == "/dev/video2"
    assert config.cameras["right"].source == "/dev/video0"


def test_multi_camera_opens_reads_statuses_and_releases():
    configs = {
        "left": CameraConfig(source="/dev/video2", threaded=False),
        "right": CameraConfig(source="/dev/video0", threaded=False),
    }
    multi = MultiCamera(configs, camera_factory=FakeCamera)

    assert multi.open() == {"left": True, "right": True}
    frames = multi.read_frames()

    assert set(frames) == {"left", "right"}
    assert frames["left"] is not None
    assert frames["left"].role == "left"
    assert frames["left"].source == "/dev/video2"
    assert frames["right"] is not None
    assert frames["right"].role == "right"
    assert frames["right"].source == "/dev/video0"
    assert multi.status() == {"left": "open", "right": "open"}

    multi.release()
    assert all(camera.released for camera in multi.cameras.values())


def test_multi_camera_reports_missing_camera_without_blocking_other_roles():
    configs = {
        "left": CameraConfig(source="missing", threaded=False),
        "right": CameraConfig(source="/dev/video0", threaded=False),
    }
    multi = MultiCamera(configs, camera_factory=FakeCamera)

    assert multi.open() == {"left": False, "right": True}
    frames = multi.read_frames()

    assert frames["left"] is None
    assert frames["right"] is not None
    assert multi.status() == {"left": "open_failed", "right": "open"}
