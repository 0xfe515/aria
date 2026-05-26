"""Configuration values for the ARIA v0 demo.

Keep hardware paths and thresholds configurable so the same code can run on a
local development machine and on the Raspberry Pi target.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class CameraConfig:
    source: int | str = os.environ.get("ARIA_CAMERA_SOURCE", "0")
    width: int = int(os.environ.get("ARIA_CAMERA_WIDTH", "1280"))
    height: int = int(os.environ.get("ARIA_CAMERA_HEIGHT", "720"))
    fps: int | None = None

    def normalized_source(self) -> int | str:
        return int(self.source) if isinstance(self.source, str) and self.source.isdigit() else self.source


@dataclass(frozen=True)
class RiskConfig:
    close_mm: int = int(os.environ.get("ARIA_RISK_CLOSE_MM", "900"))
    caution_mm: int = int(os.environ.get("ARIA_RISK_CAUTION_MM", "1600"))
    center_region_weight: float = 0.25
    large_box_area_ratio: float = 0.20


@dataclass(frozen=True)
class TofConfig:
    port: str | None = os.environ.get("ARIA_TOF_PORT")
    baud: int = int(os.environ.get("ARIA_TOF_BAUD", "115200"))
    stale_after_s: float = float(os.environ.get("ARIA_TOF_STALE_AFTER_S", "1.0"))


@dataclass(frozen=True)
class DetectorConfig:
    model_path: str | None = os.environ.get("ARIA_HEF_PATH")
    confidence_threshold: float = float(os.environ.get("ARIA_CONF_THRESHOLD", "0.35"))
    input_size: int = int(os.environ.get("ARIA_DETECTOR_INPUT_SIZE", "640"))
    quantized_input: bool = os.environ.get("ARIA_DETECTOR_QUANTIZED", "1") not in ("0", "false", "False", "FALSE")


@dataclass(frozen=True)
class UiConfig:
    box_persistence_s: float = float(os.environ.get("ARIA_BOX_PERSISTENCE_S", "0.45"))
    jpeg_quality: int = int(os.environ.get("ARIA_JPEG_QUALITY", "70"))
    stream_max_width: int = int(os.environ.get("ARIA_STREAM_MAX_WIDTH", "960"))
