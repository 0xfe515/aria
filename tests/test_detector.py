"""Tests for aria.detector without requiring Hailo hardware."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from aria.detector import HailoDetector, COCO_LABELS
from aria.fusion import BBox, Detection


def test_coco_labels_length():
    assert len(COCO_LABELS) == 80
    assert COCO_LABELS[0] == "person"


def test_bbox_unpacking():
    b = BBox(10, 20, 30, 40)
    x1, y1, x2, y2 = b
    assert (x1, y1, x2, y2) == (10, 20, 30, 40)
    assert b.width == 20
    assert b.height == 20
    assert b.area == 400


def test_bbox_from_detection():
    det = Detection(label="person", confidence=0.8, bbox=BBox(0, 0, 100, 200))
    x1, y1, x2, y2 = det.bbox
    assert x2 == 100


def test_hailo_detector_scale_bbox_abs():
    det = HailoDetector("dummy.hef")
    b = det._scale_bbox(10, 20, 30, 40, 640, 480)
    # Values >1.5 are treated as absolute on input_size=640 and scaled to frame size
    assert b.x1 == 10.0
    assert b.y1 == 15.0  # 20 * (480/640)
    assert b.x2 == 30.0
    assert b.y2 == 30.0  # 40 * (480/640)


def test_hailo_detector_scale_bbox_relative():
    det = HailoDetector("dummy.hef")
    b = det._scale_bbox(0.5, 0.25, 0.75, 0.5, 640, 480)
    assert b.x1 == 320
    assert b.x2 == 480
    assert b.y1 == 120  # 0.25 * 480
    assert b.y2 == 240  # 0.5 * 480


def test_parse_flat_detections():
    det = HailoDetector("dummy.hef", confidence_threshold=0.5)
    arr = np.array([
        [10, 10, 50, 50, 0.8, 0],
        [60, 60, 100, 100, 0.3, 0],
    ], dtype=np.float32)
    out = det._parse_flat_detections(arr, 640, 480)
    assert len(out) == 1
    assert out[0].label == "person"
    assert out[0].confidence == pytest.approx(0.8)
    assert out[0].bbox.width == 40


def test_parse_flat_detections_tuple_bbox():
    det = HailoDetector("dummy.hef", confidence_threshold=0.4)
    arr = np.array([
        [10, 10, 50, 50, 0.6, 1],
    ], dtype=np.float32)
    out = det._parse_flat_detections(arr, 640, 480)
    assert len(out) == 1
    assert out[0].label == "bicycle"


def test_candidate_class_ids():
    det = HailoDetector("dummy.hef", labels={0: "a", 5: "b"})
    assert det._candidate_class_ids(10) == [0, 5]


def test_iter_outputs_list():
    det = HailoDetector("dummy.hef")
    assert det._iter_outputs([1, 2, 3]) == [1, 2, 3]


def test_iter_outputs_dict():
    det = HailoDetector("dummy.hef")
    assert det._iter_outputs({"a": 1, "b": 2}) == [1, 2]


def test_parse_hailo_nms_postprocess_output():
    det = HailoDetector("dummy.hef", labels={0: "person"}, confidence_threshold=0.35)
    output = np.zeros((1, 80, 100, 5), dtype=np.float32)
    output[0, 0, 0] = [0.10, 0.20, 0.60, 0.70, 0.90]
    detections = det._parse_outputs({"yolov8n/yolov8_nms_postprocess": output}, 1280, 720)
    assert len(detections) == 1
    assert detections[0].label == "person"
    assert detections[0].confidence == pytest.approx(0.90)
    assert detections[0].bbox.x1 == pytest.approx(256.0)
    assert detections[0].bbox.y1 == pytest.approx(72.0)
    assert detections[0].bbox.x2 == pytest.approx(896.0)
    assert detections[0].bbox.y2 == pytest.approx(432.0)


def test_parse_skips_unconfigured_classes():
    det = HailoDetector("dummy.hef", labels={0: "person"}, confidence_threshold=0.35)
    output = np.zeros((1, 80, 100, 5), dtype=np.float32)
    output[0, 2, 0] = [0.10, 0.20, 0.60, 0.70, 0.90]
    detections = det._parse_outputs({"yolov8n/yolov8_nms_postprocess": output}, 1280, 720)
    assert detections == []


def test_looks_like_hailo_class_list():
    det = HailoDetector("dummy.hef")
    assert det._looks_like_hailo_class_list([np.zeros((0, 5))])
    assert not det._looks_like_hailo_class_list([])
    assert not det._looks_like_hailo_class_list(np.zeros((3, 5)))
