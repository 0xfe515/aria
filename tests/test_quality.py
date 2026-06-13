import pytest

from aria.quality import assess_frame_quality


def test_assess_frame_quality_skips_missing_frame():
    q = assess_frame_quality(None)
    assert q.status == "failed"
    assert q.usable is False
    assert q.reason == "missing_frame"


def test_assess_frame_quality_dark_frame_is_poor_low_light():
    np = pytest.importorskip("numpy")
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    q = assess_frame_quality(frame)
    assert q.status == "poor_low_light"
    assert q.usable is False
    assert q.under_ratio > 0.9


def test_assess_frame_quality_textured_bright_frame_is_good():
    np = pytest.importorskip("numpy")
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[:, :60] = 50
    frame[:, 60:] = 180
    q = assess_frame_quality(frame)
    assert q.status == "good"
    assert q.usable is True
    assert q.mean > 35
    assert q.std > 12
