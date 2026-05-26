import time

from aria.camera import Camera
from aria.config import CameraConfig


class FakeFrame:
    def __init__(self, value):
        self.value = value

    def copy(self):
        return FakeFrame(self.value)


class FakeCapture:
    def __init__(self):
        self.opened = True
        self.index = 0
        self.released = False

    def isOpened(self):
        return self.opened

    def set(self, *_args):
        return True

    def get(self, *_args):
        return 0

    def read(self):
        self.index += 1
        return True, FakeFrame(self.index)

    def release(self):
        self.released = True


class FakeCv2:
    CAP_V4L2 = 200
    CAP_PROP_BUFFERSIZE = 1
    CAP_PROP_FOURCC = 2
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5

    def __init__(self):
        self.capture = FakeCapture()

    def VideoCapture(self, *_args):
        return self.capture

    @staticmethod
    def VideoWriter_fourcc(*_args):
        return 0


def test_threaded_camera_returns_latest_frame(monkeypatch):
    fake_cv2 = FakeCv2()

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "cv2":
            return fake_cv2
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    camera = Camera(CameraConfig(threaded=True))

    assert camera.open() is True
    time.sleep(0.03)
    first = camera.read_frame()
    time.sleep(0.03)
    second = camera.read_frame()
    camera.release()

    assert first is not None
    assert second is not None
    assert second.index >= first.index
    assert fake_cv2.capture.released
