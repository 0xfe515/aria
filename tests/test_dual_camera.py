from aria.camera import CameraFrame, MultiCamera
from aria.config import CameraConfig, DualCameraConfig
import pytest


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


def test_multi_camera_read_combined_frame_basic():
    np = pytest.importorskip("numpy")

    class FakeCam:
        def __init__(self, config):
            self.config = config
            self.opened = False
        def open(self):
            self.opened = True
            return True
        def read_frame(self):
            if not self.opened:
                return None
            h, w = self.config.height, self.config.width
            img = np.full((h, w, 3), 128, dtype=np.uint8)
            return CameraFrame(image=img, index=1)
        def release(self):
            self.opened = False

    configs = {
        "left": CameraConfig(source="/dev/video2", width=640, height=480, threaded=False),
        "right": CameraConfig(source="/dev/video0", width=1280, height=720, threaded=False),
    }
    multi = MultiCamera(configs, camera_factory=FakeCam)
    multi.open()

    result = multi.read_combined_frame(target_height=480)
    assert result is not None
    combined, meta = result
    assert combined is not None
    h, w = combined.shape[:2]
    # 640 + 853 = 1493
    assert h == 480
    assert w == 1493
    assert meta["left"]["x_offset"] == 0
    assert meta["right"]["x_offset"] == 640
    assert meta["left"]["scale"] == 1.0
    assert round(meta["right"]["scale"], 4) == round(0.6666666666666666, 4)
    assert meta["left"]["original_shape"] == (480, 640)
    assert meta["right"]["original_shape"] == (720, 1280)

    multi.release()


def test_multi_camera_combined_frame_with_overlap():
    np = pytest.importorskip("numpy")

    class FakeCam:
        def __init__(self, config):
            self.config = config
            self.opened = False
        def open(self):
            self.opened = True
            return True
        def read_frame(self):
            if not self.opened:
                return None
            h, w = self.config.height, self.config.width
            img = np.full((h, w, 3), 128, dtype=np.uint8)
            return CameraFrame(image=img, index=1)
        def release(self):
            self.opened = False

    configs = {
        "left": CameraConfig(source="/dev/video2", width=640, height=480, threaded=False),
        "right": CameraConfig(source="/dev/video0", width=1280, height=720, threaded=False),
    }
    multi = MultiCamera(configs, camera_factory=FakeCam)
    multi.open()

    result = multi.read_combined_frame(target_height=480, overlap_px=200)
    assert result is not None
    combined, meta = result
    h, w = combined.shape[:2]
    # 640 + 853 - 200 = 1293
    assert h == 480
    assert w == 1293
    assert meta["left"]["x_offset"] == 0
    assert meta["right"]["x_offset"] == 440
    assert round(meta["right"]["scale"], 4) == round(0.6666666666666666, 4)

    multi.release()


def test_combined_frame_preserves_left_and_right_pixels():
    np = pytest.importorskip("numpy")

    class FakeCam:
        def __init__(self, config):
            self.config = config
            self.opened = False
        def open(self):
            self.opened = True
            return True
        def read_frame(self):
            if not self.opened:
                return None
            h, w = self.config.height, self.config.width
            # Left = red, right = blue
            color = (255, 0, 0) if "video2" in str(self.config.source) else (0, 0, 255)
            img = np.full((h, w, 3), color, dtype=np.uint8)
            return CameraFrame(image=img, index=1)
        def release(self):
            self.opened = False

    configs = {
        "left": CameraConfig(source="/dev/video2", width=100, height=100, threaded=False),
        "right": CameraConfig(source="/dev/video0", width=100, height=100, threaded=False),
    }
    multi = MultiCamera(configs, camera_factory=FakeCam)
    multi.open()

    result = multi.read_combined_frame(target_height=100)
    combined, _meta = result
    # Left half should be red (255,0,0), right half blue (0,0,255)
    assert np.array_equal(combined[50, 50], np.array([255, 0, 0]))
    assert np.array_equal(combined[50, 150], np.array([0, 0, 255]))

    multi.release()


def test_foveated_frame_puts_primary_in_center_and_wide_on_sides():
    np = pytest.importorskip("numpy")

    class FakeCam:
        def __init__(self, config):
            self.config = config
            self.opened = False
        def open(self):
            self.opened = True
            return True
        def read_frame(self):
            if not self.opened:
                return None
            h, w = self.config.height, self.config.width
            color = (255, 0, 0) if "wide" in str(self.config.source) else (0, 0, 255)
            img = np.full((h, w, 3), color, dtype=np.uint8)
            return CameraFrame(image=img, index=1)
        def release(self):
            self.opened = False

    configs = {
        "left": CameraConfig(source="wide", width=200, height=100, threaded=False),
        "right": CameraConfig(source="narrow", width=100, height=100, threaded=False),
    }
    multi = MultiCamera(configs, camera_factory=FakeCam)
    multi.open()

    result = multi.read_foveated_frame(primary_role="right", target_height=100, center_crop_ratio=0.5)
    assert result is not None
    combined, meta = result
    assert combined.shape[:2] == (100, 200)
    assert meta["right"]["layout"] == "center"
    assert meta["right"]["x_offset"] == 50
    assert meta["left"]["layout"] == "peripheral"
    assert meta["left"]["segments"][0] == {"x_offset": 0, "source_x": 0, "width": 50}
    assert meta["left"]["segments"][1] == {"x_offset": 150, "source_x": 150, "width": 50}
    assert np.array_equal(combined[50, 25], np.array([255, 0, 0]))
    assert np.array_equal(combined[50, 100], np.array([0, 0, 255]))
    assert np.array_equal(combined[50, 175], np.array([255, 0, 0]))

    multi.release()


def test_dual_camera_config_overlap_from_env(monkeypatch):
    monkeypatch.setenv("ARIA_DUAL_OVERLAP_PX", "150")
    config = DualCameraConfig.from_env()
    assert config.overlap_px == 150


def test_dual_camera_config_composite_mode_from_env(monkeypatch):
    monkeypatch.setenv("ARIA_DUAL_COMPOSITE_MODE", "foveated")
    monkeypatch.setenv("ARIA_FOVEATED_CENTER_CROP_RATIO", "0.6")
    config = DualCameraConfig.from_env()
    assert config.composite_mode == "foveated"
    assert config.foveated_center_crop_ratio == 0.6


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


def test_multi_camera_combined_frame_clamps_excessive_overlap():
    np = pytest.importorskip("numpy")

    class FakeCam:
        def __init__(self, config):
            self.config = config
            self.opened = False
        def open(self):
            self.opened = True
            return True
        def read_frame(self):
            if not self.opened:
                return None
            h, w = self.config.height, self.config.width
            return CameraFrame(image=np.full((h, w, 3), 128, dtype=np.uint8), index=1)
        def release(self):
            self.opened = False

    multi = MultiCamera(
        {
            "left": CameraConfig(source="left", width=100, height=100, threaded=False),
            "right": CameraConfig(source="right", width=100, height=100, threaded=False),
        },
        camera_factory=FakeCam,
    )
    multi.open()

    result = multi.read_combined_frame(target_height=100, overlap_px=500)

    assert result is not None
    combined, meta = result
    assert combined.shape[:2] == (100, 101)
    assert meta["right"]["x_offset"] == 1
    multi.release()
