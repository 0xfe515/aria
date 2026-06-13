"""Frame quality assessment for ARIA camera failover.

The goal is not to estimate lux; it is to decide whether a camera frame is
usable enough for central obstacle detection. This works for no-IR cameras by
looking at actual image information: brightness, under/over exposure, contrast,
and texture/edge content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CameraQuality:
    status: str
    mean: float = 0.0
    std: float = 0.0
    under_ratio: float = 1.0
    over_ratio: float = 0.0
    lap_var: float = 0.0
    score: float = 0.0
    reason: str = "missing_frame"

    @property
    def usable(self) -> bool:
        return self.status == "good"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mean": round(self.mean, 2),
            "std": round(self.std, 2),
            "under_ratio": round(self.under_ratio, 3),
            "over_ratio": round(self.over_ratio, 3),
            "lap_var": round(self.lap_var, 2),
            "score": round(self.score, 2),
            "reason": self.reason,
        }


def assess_frame_quality(frame: Any) -> CameraQuality:
    """Return a simple usability classification for a camera frame.

    Thresholds are intentionally conservative: switch away only when the frame
    is plainly not useful for detection (dark/flat/missing/overexposed). Use
    hysteresis in the caller to avoid flapping around boundary cases.
    """

    if frame is None or not hasattr(frame, "shape"):
        return CameraQuality(status="failed", reason="missing_frame")

    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return CameraQuality(status="unknown", reason="cv2_numpy_unavailable", under_ratio=0.0)

    try:
        if len(frame.shape) == 2:
            gray = frame
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Quality only needs a coarse signal. Downsample to keep dual-camera
        # failover cheap on Raspberry Pi while preserving brightness/texture
        # trends well enough for low-light detection.
        h, w = gray.shape[:2]
        max_dim = max(h, w)
        if max_dim > 160:
            scale = 160.0 / float(max_dim)
            gray = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        gray = gray.astype(np.uint8, copy=False)
        mean = float(gray.mean())
        std = float(gray.std())
        under_ratio = float((gray < 15).mean())
        over_ratio = float((gray > 240).mean())
        # Laplacian variance is cheap and tracks whether the frame contains
        # useful texture/edges. Dark noise alone is filtered by brightness rules.
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception as exc:
        return CameraQuality(status="failed", reason=f"analysis_error:{exc}")

    # Simple 0-100-ish usability score for status/debug display.
    brightness_score = min(max((mean - 10.0) / 60.0, 0.0), 1.0) * 35.0
    contrast_score = min(std / 35.0, 1.0) * 30.0
    texture_score = min(lap_var / 120.0, 1.0) * 25.0
    exposure_penalty = (under_ratio + over_ratio) * 35.0
    score = max(0.0, min(100.0, brightness_score + contrast_score + texture_score - exposure_penalty + 10.0))

    if over_ratio > 0.85:
        return CameraQuality("poor_overexposed", mean, std, under_ratio, over_ratio, lap_var, score, "overexposed")
    if mean < 25.0 and under_ratio > 0.60:
        return CameraQuality("poor_low_light", mean, std, under_ratio, over_ratio, lap_var, score, "dark_underexposed")
    if mean < 35.0 and std < 12.0:
        return CameraQuality("poor_low_contrast", mean, std, under_ratio, over_ratio, lap_var, score, "dark_flat")
    if std < 6.0 and lap_var < 10.0:
        return CameraQuality("poor_no_information", mean, std, under_ratio, over_ratio, lap_var, score, "flat_no_edges")
    return CameraQuality("good", mean, std, under_ratio, over_ratio, lap_var, score, "usable")
