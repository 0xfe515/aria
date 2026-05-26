"""Optional local OpenCV window UI for ARIA v0 desktop demos."""

from __future__ import annotations

import os
import time

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - target dependency check
    cv2 = None  # type: ignore

from .ui import WebDemo


class OpenCvDemo:
    """Display the shared ARIA pipeline in a local OpenCV window."""

    def __init__(self, pipeline: WebDemo, window_name: str = "ARIA v0 OpenCV Demo") -> None:
        if cv2 is None:  # pragma: no cover
            raise RuntimeError("OpenCV UI requires cv2")
        self.pipeline = pipeline
        self.window_name = window_name

    def run(self) -> int:  # pragma: no cover - GUI integration exercised on aria-core
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            print("[opencv-ui] DISPLAY/WAYLAND_DISPLAY is not set; trying OpenCV window anyway.")
        self.pipeline.start()
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        try:
            while self.pipeline._running.is_set():
                self.pipeline.update_once()
                jpeg, _status = self.pipeline._state.get()
                if jpeg:
                    arr = np.frombuffer(jpeg, dtype=np.uint8)
                    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if image is not None:
                        cv2.imshow(self.window_name, image)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                time.sleep(self.pipeline.stream_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.pipeline.stop()
            cv2.destroyWindow(self.window_name)
        return 0
