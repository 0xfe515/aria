from aria.fusion import BBox, Detection, FusedDetection, Region, RiskLevel
from aria.tracker import DetectionPersistence


def test_detection_persistence_holds_brief_miss_and_expires():
    tracker = DetectionPersistence(ttl_s=0.45)
    det = Detection(label="person", confidence=0.9, bbox=BBox(10, 10, 50, 80), class_id=0)

    first = tracker.update([det], now=10.0, image_width=100)
    assert len(first) == 1
    assert not first[0].stale

    held = tracker.update([], now=10.2, image_width=100)
    assert len(held) == 1
    assert held[0].stale
    assert held[0].confidence < 0.9
    assert held[0].bbox == det.bbox

    expired = tracker.update([], now=10.6, image_width=100)
    assert expired == []


def test_detection_persistence_matched_detection_follows_object():
    tracker = DetectionPersistence(ttl_s=0.45)
    a = Detection(label="person", confidence=0.9, bbox=BBox(10, 10, 50, 80), class_id=0)
    b = Detection(label="person", confidence=0.8, bbox=BBox(14, 12, 54, 82), class_id=0)

    tracker.update([a], now=1.0, image_width=100)
    updated = tracker.update([b], now=1.1, image_width=100)

    assert len(updated) == 1
    assert not updated[0].stale
    assert updated[0].bbox == b.bbox
    assert updated[0].confidence == 0.8


def test_detection_persistence_preserves_fused_overlay_fields():
    tracker = DetectionPersistence(ttl_s=0.45)
    det = Detection(label="chair", confidence=0.7, bbox=BBox(40, 10, 80, 90), class_id=56)
    fused = FusedDetection(det, Region.CENTER, 750, RiskLevel.DANGER)

    shown = tracker.update([fused], now=2.0, image_width=120)

    assert shown[0].region is Region.CENTER
    assert shown[0].distance_mm == 750
    assert shown[0].risk is RiskLevel.DANGER
