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
    role: str = "primary"
    source: int | str | None = None
    timestamp_s: float | None = None

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
        self._latest_timestamp_s: float | None = None
        self._last_error: str | None = None
        self._next_open_attempt_s = 0.0

    def open(self) -> bool:
        if self._cap is not None:
            return True
        now = time.monotonic()
        if now < self._next_open_attempt_s:
            return False
        try:
            import cv2  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on target install
            self.status = f"opencv_unavailable: {exc}"
            return False

        self._cv2 = cv2
        source = self.config.normalized_source()
        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if not cap.isOpened():
            self.status = f"open_failed: {source!r}"
            self._next_open_attempt_s = time.monotonic() + 1.0
            cap.release()
            return False

        if self.config.buffer_size > 0:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, self.config.buffer_size)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        if self.config.fourcc:
            # Some UVC drivers reset pixel format when width/height changes. Set
            # MJPG after size so high-FPS compressed modes are preserved.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.config.fourcc[:4]))
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
            frame = self._read_latest_frame()
        else:
            assert self._cap is not None
            ok, image = self._cap.read()
            if not ok or image is None:
                self.status = "read_failed"
                return None
            self._frame_index += 1
            self.status = "open"
            frame = CameraFrame(image=image, index=self._frame_index, source=self.config.source, timestamp_s=time.monotonic())
        if frame is not None and self.config.grayscale and self._cv2 is not None:
            # Backup/left is intentionally displayed as grayscale. Normalize to
            # 3-channel BGR after conversion so Hailo/JPEG/UI paths still receive
            # the shape they expect.
            if len(frame.image.shape) == 2:
                frame.image = self._cv2.cvtColor(frame.image, self._cv2.COLOR_GRAY2BGR)
            elif len(frame.image.shape) == 3 and frame.image.shape[2] == 1:
                frame.image = self._cv2.cvtColor(frame.image, self._cv2.COLOR_GRAY2BGR)
            elif len(frame.image.shape) == 3 and frame.image.shape[2] >= 3:
                gray = self._cv2.cvtColor(frame.image, self._cv2.COLOR_BGR2GRAY)
                frame.image = self._cv2.cvtColor(gray, self._cv2.COLOR_GRAY2BGR)
        if frame is not None and self.config.enhance_contrast:
            frame.image = self._enhance_contrast(frame.image)
        return frame

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
                self._latest_timestamp_s = time.monotonic()
                self._last_error = None
                self.status = "open"

    def _read_latest_frame(self) -> CameraFrame | None:
        with self._lock:
            image = None if self._latest_image is None else self._latest_image.copy()
            index = self._latest_index
            timestamp_s = self._latest_timestamp_s
            error = self._last_error
        if image is None:
            self.status = error or "no_frame"
            return None
        now = time.monotonic()
        if timestamp_s is not None and now - timestamp_s > self.config.stale_after_s:
            self.status = error or "stale_frame"
            return None
        self.status = "open"
        return CameraFrame(image=image, index=index, source=self.config.source, timestamp_s=timestamp_s or now)

    def _enhance_contrast(self, image: Any) -> Any:
        if self._cv2 is None or image is None:
            return image
        try:
            tile = max(1, int(self.config.clahe_tile_grid_size))
            clahe = self._cv2.createCLAHE(
                clipLimit=max(0.1, float(self.config.clahe_clip_limit)),
                tileGridSize=(tile, tile),
            )
            if len(image.shape) == 2:
                return clahe.apply(image)
            if len(image.shape) == 3 and image.shape[2] >= 3:
                lab = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2LAB)
                l_chan, a_chan, b_chan = self._cv2.split(lab)
                enhanced = self._cv2.merge((clahe.apply(l_chan), a_chan, b_chan))
                return self._cv2.cvtColor(enhanced, self._cv2.COLOR_LAB2BGR)
        except Exception:
            return image
        return image

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def list_video_nodes(dev_root: str | Path = "/dev") -> list[str]:
    """Return available Linux video node paths, sorted for stable status output."""

    return sorted(str(path) for path in Path(dev_root).glob("video*"))


class MultiCamera:
    """Role-aware wrapper for opening and reading multiple cameras safely."""

    def __init__(self, configs: dict[str, CameraConfig], camera_factory: Any = Camera) -> None:
        self.configs = dict(configs)
        self.cameras = {role: camera_factory(config) for role, config in self.configs.items()}
        self._last_frames: dict[str, CameraFrame | None] = {}

    @property
    def last_frames(self) -> dict[str, CameraFrame | None]:
        return self._last_frames

    def open(self) -> dict[str, bool]:
        return {role: bool(camera.open()) for role, camera in self.cameras.items()}

    def read_frames(self) -> dict[str, CameraFrame | None]:
        frames: dict[str, CameraFrame | None] = {}
        for role, camera in self.cameras.items():
            frame = camera.read_frame()
            if frame is not None:
                frame.role = role
                if frame.source is None:
                    frame.source = self.configs[role].source
            frames[role] = frame
        self._last_frames = frames
        return frames

    def read_combined_frame(
        self,
        target_height: int = 480,
        overlap_px: int = 0,
        frames: dict[str, CameraFrame | None] | None = None,
    ) -> tuple[Any, dict[str, Any]] | None:
        """Horizontally stitch all camera frames into one BGR image at a common height.

        Each frame is first converted to 3-channel BGR so that grayscale and
        colour cameras can be mixed safely. Returns ``(combined_image, offsets)``
        where ``offsets`` maps each role to
        ``{'x_offset': int, 'scale': float, 'original_shape': (h, w)}``.

        if ``overlap_px > 0`` the right camera overlaps the left camera by that
        many pixels (right-over-left). The canvas width shrinks accordingly so the
        overall image is narrower and more panoramic.
        """
        frames = self.read_frames() if frames is None else frames
        images: list[tuple[str, Any]] = []
        for role in sorted(frames):
            frame = frames[role]
            if frame is not None and frame.image is not None:
                images.append((role, frame.image))
        if not images:
            return None
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            return None
        resized: list[Any] = []
        offsets: dict[str, Any] = {}
        widths: list[int] = []
        for role, img in images:
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            h, w = img.shape[:2]
            scale = target_height / float(h)
            new_w = max(1, int(w * scale))
            scaled = cv2.resize(img, (new_w, target_height), interpolation=cv2.INTER_AREA)
            resized.append(scaled)
            widths.append(new_w)
            offsets[role] = {
                "x_offset": 0,
                "scale": scale,
                "original_shape": (h, w),
            }

        if overlap_px > 0 and len(resized) > 1:
            # Clamp user/env supplied overlap so a mistyped value cannot create
            # a zero/negative-width canvas and crash the demo in the field.
            safe_overlap = min(max(0, int(overlap_px)), max(0, min(widths) - 1))
            total_w = sum(widths) - safe_overlap * (len(widths) - 1)
            canvas = np.zeros((target_height, total_w, 3), dtype=np.uint8)
            x = 0
            for i, (role, scaled) in enumerate(zip([r for r, _ in images], resized)):
                w = scaled.shape[1]
                end_x = min(x + w, total_w)
                paste_w = end_x - x
                canvas[:, x:end_x] = scaled[:, :paste_w]
                offsets[role]["x_offset"] = x
                x += w
                if i < len(resized) - 1:
                    x -= safe_overlap
            return canvas, offsets
        else:
            x_offset = 0
            for role, scaled in zip([r for r, _ in images], resized):
                offsets[role]["x_offset"] = x_offset
                x_offset += scaled.shape[1]
            combined = np.hstack(resized) if len(resized) > 1 else resized[0]
            return combined, offsets

    def read_foveated_frame(
        self,
        *,
        primary_role: str,
        target_height: int = 480,
        center_crop_ratio: float = 0.5,
        frames: dict[str, CameraFrame | None] | None = None,
    ) -> tuple[Any, dict[str, Any]] | None:
        """Compose wide peripheral crops around a primary/narrow center image.

        The primary camera stays in the middle and keeps the risk-coordinate
        meaning of "center". A secondary/wide camera contributes only its left
        and right peripheral crops; its central overlap is discarded.
        """
        frames = self.read_frames() if frames is None else frames
        primary = frames.get(primary_role)
        wide_role = next(
            (role for role, frame in frames.items() if role != primary_role and frame is not None and frame.image is not None),
            None,
        )
        if primary is None or primary.image is None or wide_role is None:
            return self.read_combined_frame(target_height=target_height, frames=frames)
        wide = frames[wide_role]
        if wide is None or wide.image is None:
            return self.read_combined_frame(target_height=target_height, frames=frames)
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            return None

        def resize_bgr(img: Any) -> tuple[Any, float, tuple[int, int]]:
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            h, w = img.shape[:2]
            scale = target_height / float(h)
            new_w = max(1, int(w * scale))
            return cv2.resize(img, (new_w, target_height), interpolation=cv2.INTER_AREA), scale, (h, w)

        primary_img, primary_scale, primary_shape = resize_bgr(primary.image)
        wide_img, wide_scale, wide_shape = resize_bgr(wide.image)
        wide_w = wide_img.shape[1]
        primary_w = primary_img.shape[1]

        ratio = min(max(center_crop_ratio, 0.0), 0.95)
        center_w = int(wide_w * ratio)
        side_total = max(0, wide_w - center_w)
        left_w = side_total // 2
        right_w = side_total - left_w
        right_start = wide_w - right_w

        left_crop = wide_img[:, :left_w]
        right_crop = wide_img[:, right_start:] if right_w > 0 else wide_img[:, 0:0]
        combined = np.hstack([left_crop, primary_img, right_crop])

        offsets: dict[str, Any] = {
            wide_role: {
                "x_offset": 0,
                "scale": wide_scale,
                "original_shape": wide_shape,
                "layout": "peripheral",
                "segments": [
                    {"x_offset": 0, "source_x": 0, "width": left_w},
                    {"x_offset": left_w + primary_w, "source_x": right_start, "width": right_w},
                ],
                "discarded_center_px": center_w,
            },
            primary_role: {
                "x_offset": left_w,
                "scale": primary_scale,
                "original_shape": primary_shape,
                "layout": "center",
            },
        }
        return combined, offsets

    def status(self) -> dict[str, str]:
        return {role: getattr(camera, "status", "unknown") for role, camera in self.cameras.items()}

    def release(self) -> None:
        for camera in self.cameras.values():
            camera.release()

    def __enter__(self) -> "MultiCamera":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
