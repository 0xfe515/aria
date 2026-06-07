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
    fps: int | None = int(os.environ.get("ARIA_CAMERA_FPS", "30"))
    fourcc: str | None = os.environ.get("ARIA_CAMERA_FOURCC", "MJPG") or None
    buffer_size: int = int(os.environ.get("ARIA_CAMERA_BUFFER_SIZE", "1"))
    threaded: bool = os.environ.get("ARIA_CAMERA_THREADED", "1") not in ("0", "false", "False", "FALSE")

    def normalized_source(self) -> int | str:
        return int(self.source) if isinstance(self.source, str) and self.source.isdigit() else self.source

    @classmethod
    def from_env(cls, prefix: str = "ARIA_CAMERA") -> "CameraConfig":
        """Build a camera config from runtime environment variables.

        ``prefix`` supports role-specific cameras such as
        ``ARIA_LEFT_CAMERA_SOURCE`` while keeping the original ``ARIA_CAMERA_*``
        keys for the single-camera path.
        """

        def get(name: str, default: str) -> str:
            return os.environ.get(f"{prefix}_{name}", default)

        fps = get("FPS", "30")
        return cls(
            source=get("SOURCE", "0"),
            width=int(get("WIDTH", "1280")),
            height=int(get("HEIGHT", "720")),
            fps=int(fps) if fps else None,
            fourcc=get("FOURCC", "MJPG") or None,
            buffer_size=int(get("BUFFER_SIZE", "1")),
            threaded=get("THREADED", "1") not in ("0", "false", "False", "FALSE"),
        )


@dataclass(frozen=True)
class DualCameraConfig:
    cameras: dict[str, CameraConfig]
    primary_role: str = "right"

    @classmethod
    def from_env(cls) -> "DualCameraConfig":
        """Return ARIA's current left/right camera configuration."""

        left = _role_camera_from_env("left", "/dev/video2")
        right = _role_camera_from_env("right", "/dev/video0")
        return cls(cameras={"left": left, "right": right}, primary_role=os.environ.get("ARIA_PRIMARY_CAMERA", "right"))


def _role_camera_from_env(role: str, default_source: str) -> CameraConfig:
    prefix = f"ARIA_{role.upper()}_CAMERA"
    config = CameraConfig.from_env(prefix)
    if f"{prefix}_SOURCE" in os.environ:
        return config
    return CameraConfig(
        source=default_source,
        width=config.width,
        height=config.height,
        fps=config.fps,
        fourcc=config.fourcc,
        buffer_size=config.buffer_size,
        threaded=config.threaded,
    )


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
    jpeg_quality: int = int(os.environ.get("ARIA_JPEG_QUALITY", "60"))
    stream_max_width: int = int(os.environ.get("ARIA_STREAM_MAX_WIDTH", "640"))
