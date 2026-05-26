"""Hailo-8L YOLOv8n detector adapter for ARIA v0."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

from .fusion import BBox, Detection


COCO_LABELS: dict[int, str] = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane",
    5: "bus", 6: "train", 7: "truck", 8: "boat", 9: "traffic light",
    10: "fire hydrant", 11: "stop sign", 12: "parking meter", 13: "bench",
    14: "bird", 15: "cat", 16: "dog", 17: "horse", 18: "sheep", 19: "cow",
    20: "elephant", 21: "bear", 22: "zebra", 23: "giraffe", 24: "backpack",
    25: "umbrella", 26: "handbag", 27: "tie", 28: "suitcase", 29: "frisbee",
    30: "skis", 31: "snowboard", 32: "sports ball", 33: "kite",
    34: "baseball bat", 35: "baseball glove", 36: "skateboard",
    37: "surfboard", 38: "tennis racket", 39: "bottle",
    40: "wine glass", 41: "cup", 42: "fork", 43: "knife", 44: "spoon",
    45: "bowl", 46: "banana", 47: "apple", 48: "sandwich", 49: "orange",
    50: "broccoli", 51: "carrot", 52: "hot dog", 53: "pizza", 54: "donut",
    55: "cake", 56: "chair", 57: "couch", 58: "potted plant", 59: "bed",
    60: "dining table", 61: "toilet", 62: "tv", 63: "laptop", 64: "mouse",
    65: "remote", 66: "keyboard", 67: "cell phone", 68: "microwave",
    69: "oven", 70: "toaster", 71: "sink", 72: "refrigerator", 73: "book",
    74: "clock", 75: "vase", 76: "scissors", 77: "teddy bear",
    78: "hair drier", 79: "toothbrush",
}


class HailoDetector:
    """Minimal HailoRT detector adapter.

    Supports Hailo YOLO NMS outputs as well as flat Nx6 tensors.
    """

    def __init__(
        self,
        model_path: str | Path,
        labels: dict[int, str] | None = None,
        input_size: int = 640,
        confidence_threshold: float = 0.35,
        quantized_input: bool = True,
    ) -> None:
        self.model_path = Path(model_path)
        self.labels = labels or COCO_LABELS
        self.enabled_class_ids = set(self.labels)
        self.input_size = input_size
        self.confidence_threshold = confidence_threshold
        self.quantized_input = quantized_input
        self._hpf: Any | None = None
        self._target_context: Any | None = None
        self._target: Any | None = None
        self._network_group: Any | None = None
        self._input_vstreams_params: Any | None = None
        self._output_vstreams_params: Any | None = None
        self._input_name: str | None = None
        self._activation_context: Any | None = None
        self._infer_pipeline_context: Any | None = None
        self._infer_pipeline: Any | None = None
        self.last_timing_ms: dict[str, float] = {}

    def open(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(f"HEF model not found: {self.model_path}")
        try:
            import hailo_platform as hpf
        except ImportError as exc:
            raise RuntimeError(
                "Hailo Python API is required. Install HailoRT/hailo-all on Raspberry Pi 5."
            ) from exc

        self._hpf = hpf
        hef = hpf.HEF(str(self.model_path))
        self._target_context = hpf.VDevice()
        self._target = self._target_context.__enter__()
        configure_params = hpf.ConfigureParams.create_from_hef(
            hef, interface=hpf.HailoStreamInterface.PCIe
        )
        self._network_group = self._target.configure(hef, configure_params)[0]
        self._input_name = hef.get_input_vstream_infos()[0].name
        input_format = hpf.FormatType.UINT8 if self.quantized_input else hpf.FormatType.FLOAT32
        self._input_vstreams_params = hpf.InputVStreamParams.make_from_network_group(
            self._network_group,
            quantized=self.quantized_input,
            format_type=input_format,
        )
        self._output_vstreams_params = hpf.OutputVStreamParams.make_from_network_group(
            self._network_group,
            quantized=False,
            format_type=hpf.FormatType.FLOAT32,
        )
        self._activation_context = self._network_group.activate(self._network_group.create_params())
        self._activation_context.__enter__()
        self._infer_pipeline_context = hpf.InferVStreams(
            self._network_group,
            self._input_vstreams_params,
            self._output_vstreams_params,
        )
        self._infer_pipeline = self._infer_pipeline_context.__enter__()

    def close(self) -> None:
        if self._infer_pipeline_context is not None:
            self._infer_pipeline_context.__exit__(None, None, None)
        if self._activation_context is not None:
            self._activation_context.__exit__(None, None, None)
        if self._target_context is not None:
            self._target_context.__exit__(None, None, None)
        self._infer_pipeline_context = None
        self._infer_pipeline = None
        self._activation_context = None
        self._target_context = None
        self._target = None

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._infer_pipeline is None or self._input_name is None:
            raise RuntimeError("HailoDetector.open() must be called before detect().")

        original_h, original_w = frame.shape[:2]
        started_at = time.perf_counter()
        input_tensor = self._preprocess(frame)
        preprocessed_at = time.perf_counter()
        results = self._infer_pipeline.infer({self._input_name: input_tensor})
        inferred_at = time.perf_counter()
        detections = self._parse_outputs(results, original_w, original_h)
        parsed_at = time.perf_counter()

        self.last_timing_ms = {
            "preprocess": (preprocessed_at - started_at) * 1000.0,
            "infer": (inferred_at - preprocessed_at) * 1000.0,
            "parse": (parsed_at - inferred_at) * 1000.0,
            "detector": (parsed_at - started_at) * 1000.0,
        }
        return detections

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        if cv2 is None:
            raise RuntimeError("cv2 is required for detector preprocessing")
        resized = cv2.resize(frame, (self.input_size, self.input_size))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        if self.quantized_input:
            return np.expand_dims(np.ascontiguousarray(rgb), axis=0)
        return np.expand_dims(rgb.astype(np.float32), axis=0)

    def _parse_outputs(self, outputs: Any, frame_w: int, frame_h: int) -> list[Detection]:
        detections: list[Detection] = []
        for output in self._iter_outputs(outputs):
            if self._looks_like_batched_hailo_class_list(output):
                for batch_output in output:
                    detections.extend(self._parse_hailo_class_list(batch_output, frame_w, frame_h))
                continue
            if self._looks_like_hailo_class_list(output):
                detections.extend(self._parse_hailo_class_list(output, frame_w, frame_h))
                continue
            arr = np.asarray(output)
            if arr.ndim >= 1 and arr.shape[0] == 1:
                arr = arr[0]
            detections.extend(self._parse_array(arr, frame_w, frame_h))
        return detections

    def _parse_array(self, arr: np.ndarray, frame_w: int, frame_h: int) -> list[Detection]:
        if arr.ndim == 2 and arr.shape[-1] >= 6:
            return self._parse_flat_detections(arr, frame_w, frame_h)
        if arr.ndim == 3 and arr.shape[-1] >= 5:
            return self._parse_hailo_nms_detections(arr, frame_w, frame_h)
        return []

    def _parse_flat_detections(self, arr: np.ndarray, frame_w: int, frame_h: int) -> list[Detection]:
        detections: list[Detection] = []
        scored = arr[arr[:, 4] >= self.confidence_threshold]
        for row in scored:
            x1, y1, x2, y2, score, class_id = row[:6]
            detection = self._make_detection(
                int(class_id),
                float(score),
                float(x1),
                float(y1),
                float(x2),
                float(y2),
                frame_w,
                frame_h,
            )
            if detection:
                detections.append(detection)
        return detections

    def _parse_hailo_nms_detections(self, arr: np.ndarray, frame_w: int, frame_h: int) -> list[Detection]:
        detections: list[Detection] = []
        for class_id in self._candidate_class_ids(len(arr)):
            class_detections = arr[class_id]
            scored = class_detections[class_detections[:, 4] >= self.confidence_threshold]
            for row in scored:
                detection = self._make_hailo_nms_detection(class_id, row, frame_w, frame_h)
                if detection:
                    detections.append(detection)
        return detections

    def _parse_hailo_class_list(self, output: Any, frame_w: int, frame_h: int) -> list[Detection]:
        detections: list[Detection] = []
        for class_id in self._candidate_class_ids(len(output)):
            class_detections = output[class_id]
            arr = np.asarray(class_detections)
            if arr.size == 0:
                continue
            if arr.ndim == 1:
                arr = np.expand_dims(arr, axis=0)
            if arr.ndim != 2 or arr.shape[-1] < 5:
                continue
            scored = arr[arr[:, 4] >= self.confidence_threshold]
            for row in scored:
                detection = self._make_hailo_nms_detection(class_id, row, frame_w, frame_h)
                if detection:
                    detections.append(detection)
        return detections

    def _make_hailo_nms_detection(
        self,
        class_id: int,
        row: np.ndarray,
        frame_w: int,
        frame_h: int,
    ) -> Detection | None:
        y1, x1, y2, x2, score = row[:5]
        return self._make_detection(
            class_id,
            float(score),
            float(x1),
            float(y1),
            float(x2),
            float(y2),
            frame_w,
            frame_h,
        )

    def _make_detection(
        self,
        class_id: int,
        score: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        frame_w: int,
        frame_h: int,
    ) -> Detection | None:
        if self.enabled_class_ids and class_id not in self.enabled_class_ids:
            return None
        if score < self.confidence_threshold:
            return None
        bbox = self._scale_bbox(x1, y1, x2, y2, frame_w, frame_h)
        if bbox.width <= 0:
            return None
        return Detection(
            class_id=class_id,
            label=self.labels.get(class_id, f"class_{class_id}"),
            confidence=score,
            bbox=bbox,
        )

    def _candidate_class_ids(self, class_count: int) -> list[int]:
        if not self.enabled_class_ids:
            return list(range(class_count))
        return [class_id for class_id in sorted(self.enabled_class_ids) if class_id < class_count]

    def _iter_outputs(self, outputs: Any) -> list[Any]:
        if isinstance(outputs, dict):
            return list(outputs.values())
        if isinstance(outputs, (list, tuple)):
            return list(outputs)
        return [outputs]

    def _looks_like_hailo_class_list(self, output: Any) -> bool:
        if not isinstance(output, (list, tuple)):
            return False
        if len(output) == 0:
            return False
        try:
          first = np.asarray(output[0])
        except ValueError:
            return False
        if first.ndim == 0:
            return False
        return first.size == 0 or first.shape[-1] >= 5

    def _looks_like_batched_hailo_class_list(self, output: Any) -> bool:
        if not isinstance(output, (list, tuple)):
            return False
        if len(output) == 0:
            return False
        return self._looks_like_hailo_class_list(output[0])

    def _scale_bbox(self, x1: float, y1: float, x2: float, y2: float, frame_w: int, frame_h: int) -> BBox:
        if max(x1, x2) <= 1.5 and max(y1, y2) <= 1.5:
            x1, x2 = x1 * frame_w, x2 * frame_w
            y1, y2 = y1 * frame_h, y2 * frame_h
        else:
            x_scale = frame_w / float(self.input_size)
            y_scale = frame_h / float(self.input_size)
            x1, x2 = x1 * x_scale, x2 * x_scale
            y1, y2 = y1 * y_scale, y2 * y_scale
        return BBox(
            x1=max(0.0, min(float(frame_w), x1)),
            y1=max(0.0, min(float(frame_h), y1)),
            x2=max(0.0, min(float(frame_w), x2)),
            y2=max(0.0, min(float(frame_h), y2)),
        )
