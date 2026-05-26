"""OpenCV camera adapter for ARIA v0."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    """Small wrapper around ``cv2.VideoCapture`` with safe status reporting."""

    def __init__(self, config: CameraConfig | None = None) -> None:
        self.config = config or CameraConfig()
        self._cv2: Any | None = None
        self._cap: Any | None = None
        self._frame_index = 0
        self.status = "not_opened"

    def open(self) -> bool:
        if self._cap is not None:
            return True
        try:
            import cv2  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on target install
            self.status = f"opencv_unavailable: {exc}"
            return False

        self._cv2 = cv2
        cap = cv2.VideoCapture(self.config.normalized_source())
        if not cap.isOpened():
            self.status = f"open_failed: {self.config.normalized_source()!r}"
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
        return True

    def read_frame(self) -> CameraFrame | None:
        if self._cap is None and not self.open():
            return None
        assert self._cap is not None
        ok, image = self._cap.read()
        if not ok or image is None:
            self.status = "read_failed"
            return None
        self._frame_index += 1
        self.status = "open"
        return CameraFrame(image=image, index=self._frame_index)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self.status = "released"

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def list_video_nodes(dev_root: str | Path = "/dev") -> list[str]:
    """Return available Linux video node paths, sorted for stable status output."""

    return sorted(str(path) for path in Path(dev_root).glob("video*"))
