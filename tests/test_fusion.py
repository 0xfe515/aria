from aria.config import RiskConfig
from aria.fusion import Detection, Region, RiskLevel, TofFrame, fuse_detection, image_region, score_risk


def grid(value: int):
    return tuple(tuple(value for _ in range(8)) for _ in range(8))


def test_image_region_splits_width_into_thirds():
    assert image_region(10, 300) is Region.LEFT
    assert image_region(150, 300) is Region.CENTER
    assert image_region(290, 300) is Region.RIGHT


def test_tof_region_distance_uses_median_valid_columns():
    rows = []
    for _ in range(8):
        rows.append((1000, 1000, 1500, 1500, 1500, 1500, 2200, 2200))
    tof = TofFrame(tuple(rows))
    assert tof.distance_for_region(Region.LEFT) == 1000
    assert tof.distance_for_region(Region.CENTER) == 1500
    assert tof.distance_for_region(Region.RIGHT) == 2200


def test_tof_region_distance_falls_back_to_any_valid_zone():
    rows = []
    for _ in range(8):
        rows.append((900, 1000, None, None, None, None, 3000, 3100))
    tof = TofFrame(tuple(rows))

    assert tof.distance_for_region(Region.CENTER) == 900


def test_missing_distance_is_unknown_not_clear():
    assert score_risk(region=Region.CENTER, distance_mm=None) is RiskLevel.UNKNOWN


def test_center_region_is_more_conservative():
    cfg = RiskConfig(close_mm=900, caution_mm=1600, center_region_weight=0.25)
    assert score_risk(region=Region.LEFT, distance_mm=2000, config=cfg) is RiskLevel.CLEAR
    assert score_risk(region=Region.CENTER, distance_mm=2000, config=cfg) is RiskLevel.CAUTION


def test_large_box_and_center_motion_raise_risk():
    cfg = RiskConfig(close_mm=900, caution_mm=1600, center_region_weight=0.0, large_box_area_ratio=0.20)
    assert score_risk(region=Region.LEFT, distance_mm=1800, box_area_ratio=0.10, config=cfg) is RiskLevel.CLEAR
    assert score_risk(region=Region.LEFT, distance_mm=1800, box_area_ratio=0.25, config=cfg) is RiskLevel.CAUTION
    assert score_risk(region=Region.LEFT, distance_mm=1800, moving_toward_center=True, config=cfg) is RiskLevel.CAUTION


def test_fuse_detection_maps_bbox_to_region_distance_and_risk():
    det = Detection(label="person", confidence=0.9, bbox=(120, 100, 180, 260))
    tof = TofFrame(grid(800))
    fused = fuse_detection(det, (480, 640, 3), tof)
    assert fused.region is Region.LEFT
    assert fused.distance_mm == 800
    assert fused.risk is RiskLevel.DANGER
