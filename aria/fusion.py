"""Detection, ToF zone association, and rule-based risk scoring for ARIA v0."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from statistics import median

from .config import RiskConfig


class Region(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class RiskLevel(str, Enum):
    UNKNOWN = "unknown"
    CLEAR = "clear"
    CAUTION = "caution"
    DANGER = "danger"


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in image pixels

    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0

    def area_ratio(self, image_shape: tuple[int, int] | tuple[int, int, int]) -> float:
        height, width = image_shape[:2]
        x1, y1, x2, y2 = self.bbox
        box_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        image_area = max(1.0, float(width * height))
        return box_area / image_area


@dataclass(frozen=True)
class TofFrame:
    distances_mm: tuple[tuple[int | None, ...], ...]
    sequence: int | None = None
    status: int = 0

    def distance_for_region(self, region: Region) -> int | None:
        """Return the median valid distance in the 8x8 columns mapped to a region."""

        if len(self.distances_mm) != 8 or any(len(row) != 8 for row in self.distances_mm):
            return None
        # Adjacent regions intentionally overlap one ToF column to create soft
        # boundaries on the coarse 8-column VL53L5CX grid.
        columns = {
            Region.LEFT: range(0, 3),
            Region.CENTER: range(2, 6),
            Region.RIGHT: range(5, 8),
        }[region]
        values: list[int] = []
        for row in self.distances_mm:
            for col in columns:
                value = row[col]
                if value is not None and value > 0:
                    values.append(value)
        return int(median(values)) if values else None


def image_region(x: float, image_width: int) -> Region:
    if image_width <= 0:
        return Region.CENTER
    if x < image_width / 3.0:
        return Region.LEFT
    if x > image_width * 2.0 / 3.0:
        return Region.RIGHT
    return Region.CENTER


def score_risk(
    *,
    region: Region,
    distance_mm: int | None,
    box_area_ratio: float = 0.0,
    moving_toward_center: bool = False,
    config: RiskConfig | None = None,
) -> RiskLevel:
    """Simple safe-biased v0 risk rule.

    Missing distance is explicit UNKNOWN, not CLEAR. The UI can surface this as a
    sensor warning while continuing camera/detector operation.
    """

    cfg = config or RiskConfig()
    if distance_mm is None or not math.isfinite(distance_mm) or distance_mm <= 0:
        return RiskLevel.UNKNOWN

    effective_distance = float(distance_mm)
    if region is Region.CENTER:
        effective_distance *= 1.0 - cfg.center_region_weight
    if box_area_ratio >= cfg.large_box_area_ratio:
        effective_distance *= 0.85
    if moving_toward_center:
        effective_distance *= 0.85

    if effective_distance <= cfg.close_mm:
        return RiskLevel.DANGER
    if effective_distance <= cfg.caution_mm:
        return RiskLevel.CAUTION
    return RiskLevel.CLEAR


@dataclass(frozen=True)
class FusedDetection:
    detection: Detection
    region: Region
    distance_mm: int | None
    risk: RiskLevel


def fuse_detection(
    detection: Detection,
    image_shape: tuple[int, int] | tuple[int, int, int],
    tof: TofFrame | None,
    *,
    moving_toward_center: bool = False,
    config: RiskConfig | None = None,
) -> FusedDetection:
    height, width = image_shape[:2]
    del height
    cx, _cy = detection.center()
    region = image_region(cx, width)
    distance = tof.distance_for_region(region) if tof is not None else None
    risk = score_risk(
        region=region,
        distance_mm=distance,
        box_area_ratio=detection.area_ratio(image_shape),
        moving_toward_center=moving_toward_center,
        config=config,
    )
    return FusedDetection(detection=detection, region=region, distance_mm=distance, risk=risk)
