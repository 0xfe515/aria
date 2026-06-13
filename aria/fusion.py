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
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float

    def __iter__(self):
        return iter((self.x1, self.y1, self.x2, self.y2))

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox: BBox | tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    class_id: int = 0

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


@dataclass(frozen=True)
class TofFrameSet:
    """One or three VL53L5CX frames mapped to ARIA risk regions.

    A single connected ToF is treated as the legacy center/global sensor for all
    regions. With three sensors, each physical sensor owns its matching left,
    center, or right region.
    """

    frames: dict[str, TofFrame]

    def distance_for_region(self, region: Region) -> int | None:
        if not self.frames:
            return None
        if len(self.frames) == 1:
            frame = next(iter(self.frames.values()))
            return frame.distance_for_region(Region.CENTER)
        role = region.value
        frame = self.frames.get(role) or self.frames.get("center")
        if frame is None:
            return None
        return frame.distance_for_region(Region.CENTER)


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


def transform_fused_detection(fd: FusedDetection, scale: float, dx: float = 0, dy: float = 0) -> FusedDetection:
    """Return a new FusedDetection with its bbox scaled and translated."""
    det = fd.detection
    bbox = det.bbox
    if isinstance(bbox, BBox):
        x1, y1, x2, y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2
    else:
        x1, y1, x2, y2 = bbox
    new_bbox = BBox(x1 * scale + dx, y1 * scale + dy, x2 * scale + dx, y2 * scale + dy)
    new_det = Detection(label=det.label, confidence=det.confidence, bbox=new_bbox, class_id=det.class_id)
    return FusedDetection(detection=new_det, region=fd.region, distance_mm=fd.distance_mm, risk=fd.risk)


def fuse_detection(
    detection: Detection,
    image_shape: tuple[int, int] | tuple[int, int, int],
    tof: TofFrame | TofFrameSet | None,
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
