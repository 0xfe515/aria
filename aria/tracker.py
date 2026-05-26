"""Short-lived detection persistence for stable ARIA demo overlays.

The tracker intentionally keeps boxes for only a brief TTL. Fresh detections
replace matched tracks every frame, so boxes follow objects while short Hailo
misses do not make the UI flicker.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from .fusion import BBox, Region, RiskLevel, image_region


@dataclass(frozen=True)
class DisplayDetection:
    label: str
    confidence: float
    bbox: BBox
    class_id: int = 0
    region: Region | None = None
    distance_mm: int | None = None
    risk: RiskLevel | str | None = None
    stale: bool = False
    age_s: float = 0.0


@dataclass
class _Track:
    item: DisplayDetection
    first_seen: float
    last_seen: float


def _bbox_from_any(value: Any) -> BBox:
    x1, y1, x2, y2 = value
    return BBox(float(x1), float(y1), float(x2), float(y2))


def _iou(a: BBox, b: BBox) -> float:
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _display_from_any(item: Any, image_width: int | None = None) -> DisplayDetection:
    detection = getattr(item, "detection", item)
    bbox = _bbox_from_any(getattr(detection, "bbox", (0.0, 0.0, 0.0, 0.0)))
    region = getattr(item, "region", None)
    if region is None and image_width:
        region = image_region(bbox.center_x, image_width)
    return DisplayDetection(
        label=str(getattr(detection, "label", "obj")),
        confidence=float(getattr(detection, "confidence", 0.0)),
        bbox=bbox,
        class_id=int(getattr(detection, "class_id", 0)),
        region=region,
        distance_mm=getattr(item, "distance_mm", None),
        risk=getattr(item, "risk", None),
    )


class DetectionPersistence:
    """Maintain recent detections for a short, non-distracting overlay TTL."""

    def __init__(self, ttl_s: float = 0.45, min_iou: float = 0.20) -> None:
        self.ttl_s = max(0.0, ttl_s)
        self.min_iou = min_iou
        self._tracks: list[_Track] = []

    def update(
        self,
        detections: list[Any],
        *,
        now: float | None = None,
        image_width: int | None = None,
    ) -> list[DisplayDetection]:
        now = time.monotonic() if now is None else now
        fresh = [_display_from_any(det, image_width=image_width) for det in detections]
        matched_track_ids: set[int] = set()
        output: list[DisplayDetection] = []

        for det in fresh:
            match_index = self._find_match(det, matched_track_ids)
            if match_index is None:
                self._tracks.append(_Track(item=det, first_seen=now, last_seen=now))
            else:
                track = self._tracks[match_index]
                track.item = det
                track.last_seen = now
                matched_track_ids.add(match_index)
            output.append(det)

        kept: list[_Track] = []
        for index, track in enumerate(self._tracks):
            age = now - track.last_seen
            if age <= self.ttl_s:
                kept.append(track)
                if index not in matched_track_ids and age > 0:
                    output.append(self._make_stale(track.item, age))
        self._tracks = kept
        return output

    def clear(self) -> None:
        self._tracks.clear()

    def _find_match(self, det: DisplayDetection, used: set[int]) -> int | None:
        best_iou = 0.0
        best_index: int | None = None
        for index, track in enumerate(self._tracks):
            if index in used:
                continue
            if track.item.class_id != det.class_id and track.item.label != det.label:
                continue
            score = _iou(track.item.bbox, det.bbox)
            if score > best_iou:
                best_iou = score
                best_index = index
        return best_index if best_index is not None and best_iou >= self.min_iou else None

    def _make_stale(self, det: DisplayDetection, age: float) -> DisplayDetection:
        if self.ttl_s <= 0:
            confidence = det.confidence
        else:
            confidence = max(0.0, det.confidence * (1.0 - min(age / self.ttl_s, 1.0)))
        return DisplayDetection(
            label=det.label,
            confidence=confidence,
            bbox=det.bbox,
            class_id=det.class_id,
            region=det.region,
            distance_mm=det.distance_mm,
            risk=det.risk,
            stale=True,
            age_s=age,
        )
