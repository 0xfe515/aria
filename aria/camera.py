"""OpenCV camera adapter for ARIA v0."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any

from .config import CameraConfig


@dataclass
class CameraFrame:
    image: Any
    index: int

    @property
    def shape(self) -> tuple[int, ...] | None:
        return getattr(self.image, "shape", None)


class Camera:
    """Small wrapper around ``cv2.VideoCapture`` with safe status reporting.

    When ``CameraConfig.threaded`` is enabled a background reader continuously
    drains the UVC device and ``read_frame()`` returns the latest frame. This is
    copied from the older prototype because it reduces capture latency and stale
    frame buildup when Hailo inference or web JPEG encoding takes longer than a
    camera frame interval.
    """

    def __init__(self, config: CameraConfig | None = None) -> None:
        self.config = config or CameraConfig()
        self._cv2: Any | None = None
        self._cap: Any | None = None
        self._frame_index = 0
        self.status = "not_opened"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._latest_image: Any | None = None
        self._latest_index = 0
        self._last_error: str | None = None

    def open(self) -> bool:
        if self._cap is not None:
            return True
        try:
            import cv2  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on target install
            self.status = f"opencv_unavailable: {exc}"
            return False

        self._cv2 = cv2
        source = self.config.normalized_source()
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2) if isinstance(source, int) else cv2.VideoCapture(source)
        if not cap.isOpened():
            self.status = f"open_failed: {source!r}"
            cap.release()
            return False

        if self.config.buffer_size > 0:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, self.config.buffer_size)
        if self.config.fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.config.fourcc[:4]))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        if self.config.fps:
            cap.set(cv2.CAP_PROP_FPS, self.config.fps)
        self._cap = cap
        self.status = "open"
        self._log_actual_settings()
        if self.config.threaded:
            self._start_reader_thread()
        return True

    def read_frame(self) -> CameraFrame | None:
        if self._cap is None and not self.open():
            return None
        if self.config.threaded:
            return self._read_latest_frame()
        assert self._cap is not None
        ok, image = self._cap.read()
        if not ok or image is None:
            self.status = "read_failed"
            return None
        self._frame_index += 1
        self.status = "open"
        return CameraFrame(image=image, index=self._frame_index)

    def release(self) -> None:
        self._stop_event.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
            self._reader_thread = None
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._latest_image = None
        self.status = "released"

    def _log_actual_settings(self) -> None:
        if self._cap is None or self._cv2 is None:
            return
        try:
            fourcc_int = int(self._cap.get(self._cv2.CAP_PROP_FOURCC))
            fourcc = "".join(chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4)).strip()
            width = self._cap.get(self._cv2.CAP_PROP_FRAME_WIDTH)
            height = self._cap.get(self._cv2.CAP_PROP_FRAME_HEIGHT)
            fps = self._cap.get(self._cv2.CAP_PROP_FPS)
            self.status = f"open {fourcc or 'unknown'} {width:.0f}x{height:.0f}@{fps:.1f}"
        except Exception:
            self.status = "open"

    def _start_reader_thread(self) -> None:
        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="aria-camera-reader", daemon=True)
        self._reader_thread.start()
        deadline = time.monotonic() + 2.0
        while self._latest_image is None and time.monotonic() < deadline:
            if self._last_error:
                self.status = self._last_error
                return
            time.sleep(0.01)

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._cap is None:
                return
            ok, image = self._cap.read()
            if not ok or image is None:
                self._last_error = "read_failed"
                time.sleep(0.01)
                continue
            with self._lock:
                self._frame_index += 1
                self._latest_index = self._frame_index
                self._latest_image = image
                self._last_error = None
                self.status = "open"

    def _read_latest_frame(self) -> CameraFrame | None:
        with self._lock:
            image = None if self._latest_image is None else self._latest_image.copy()
            index = self._latest_index
            error = self._last_error
        if image is None:
            self.status = error or "no_frame"
            return None
        self.status = "open"
        return CameraFrame(image=image, index=index)

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def list_video_nodes(dev_root: str | Path = "/dev") -> list[str]:
    """Return available Linux video node paths, sorted for stable status output."""

    return sorted(str(path) for path in Path(dev_root).glob("video*"))
