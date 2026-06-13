"""Configuration values for the ARIA v0 demo.

Keep hardware paths and thresholds configurable so the same code can run on a
local development machine and on the Raspberry Pi target.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

_FALSE_VALUES = ("0", "false", "False", "FALSE", "no", "No", "NO", "")
_TRUE_VALUES = ("1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON")


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return _parse_bool(raw, default)


def _parse_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_bool(raw: str, default: bool = False) -> bool:
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return default


@dataclass(frozen=True)
class CameraConfig:
    source: int | str = _env_str("ARIA_CAMERA_SOURCE", "0")
    width: int = _env_int("ARIA_CAMERA_WIDTH", 1280)
    height: int = _env_int("ARIA_CAMERA_HEIGHT", 720)
    fps: int | None = _env_int("ARIA_CAMERA_FPS", 30)
    fourcc: str | None = _env_str("ARIA_CAMERA_FOURCC", "MJPG") or None
    buffer_size: int = _env_int("ARIA_CAMERA_BUFFER_SIZE", 1)
    threaded: bool = _env_bool("ARIA_CAMERA_THREADED", True)
    grayscale: bool = _env_bool("ARIA_CAMERA_GRAYSCALE", False)
    stale_after_s: float = _env_float("ARIA_CAMERA_STALE_AFTER_S", 0.75)
    failure_hold_s: float = _env_float("ARIA_CAMERA_FAILURE_HOLD_S", 2.0)

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
            width=_parse_int(get("WIDTH", "1280"), 1280),
            height=_parse_int(get("HEIGHT", "720"), 720),
            fps=_parse_int(fps, 30) if fps else None,
            fourcc=get("FOURCC", "MJPG") or None,
            buffer_size=_parse_int(get("BUFFER_SIZE", "1"), 1),
            threaded=_parse_bool(get("THREADED", "1"), True),
            grayscale=_parse_bool(get("GRAYSCALE", "0"), False),
            stale_after_s=float(get("STALE_AFTER_S", "0.75") or "0.75"),
            failure_hold_s=float(get("FAILURE_HOLD_S", "2.0") or "2.0"),
        )


@dataclass(frozen=True)
class DualCameraConfig:
    cameras: dict[str, CameraConfig]
    primary_role: str = "right"
    overlap_px: int = 0
    composite_mode: str = "foveated"
    foveated_center_crop_ratio: float = 0.25

    @classmethod
    def from_env(cls) -> "DualCameraConfig":
        """Return ARIA's current left/right camera configuration."""

        left = _role_camera_from_env("left", "/dev/video2", default_grayscale=True)
        right = _role_camera_from_env("right", "/dev/video0")
        return cls(
            cameras={"left": left, "right": right},
            primary_role=os.environ.get("ARIA_PRIMARY_CAMERA", "right"),
            overlap_px=_env_int("ARIA_DUAL_OVERLAP_PX", 0),
            composite_mode=os.environ.get("ARIA_DUAL_COMPOSITE_MODE", "foveated"),
            foveated_center_crop_ratio=_env_float("ARIA_FOVEATED_CENTER_CROP_RATIO", 0.25),
        )


def _role_camera_from_env(role: str, default_source: str, default_grayscale: bool = False) -> CameraConfig:
    prefix = f"ARIA_{role.upper()}_CAMERA"
    config = CameraConfig.from_env(prefix)
    if f"{prefix}_SOURCE" in os.environ:
        source = config.source
    else:
        source = default_source
    return CameraConfig(
        source=source,
        width=config.width,
        height=config.height,
        fps=config.fps,
        fourcc=config.fourcc,
        buffer_size=config.buffer_size,
        threaded=config.threaded,
        grayscale=default_grayscale or config.grayscale,
        stale_after_s=config.stale_after_s,
        failure_hold_s=config.failure_hold_s,
    )


@dataclass(frozen=True)
class RiskConfig:
    close_mm: int = _env_int("ARIA_RISK_CLOSE_MM", 900)
    caution_mm: int = _env_int("ARIA_RISK_CAUTION_MM", 2000)
    center_region_weight: float = 0.25
    large_box_area_ratio: float = 0.20


@dataclass(frozen=True)
class TofConfig:
    port: str | None = os.environ.get("ARIA_TOF_PORT")
    baud: int = _env_int("ARIA_TOF_BAUD", 115200)
    stale_after_s: float = _env_float("ARIA_TOF_STALE_AFTER_S", 1.0)
    expected_sensors: tuple[str, ...] = tuple(
        role.strip()
        for role in os.environ.get("ARIA_TOF_EXPECTED_SENSORS", "center").split(",")
        if role.strip()
    )
    xshut_pins: dict[str, int] = None  # type: ignore[assignment]
    addresses: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        default_xshut = {"left": 10, "center": 11, "right": 12}
        default_addr = {"left": 0x2A, "center": 0x29, "right": 0x2B}
        object.__setattr__(self, "xshut_pins", self.xshut_pins or _env_role_ints("ARIA_TOF_XSHUT_PINS", default_xshut))
        object.__setattr__(self, "addresses", self.addresses or _env_role_ints("ARIA_TOF_ADDRESSES", default_addr, base=0))


@dataclass(frozen=True)
class HapticConfig:
    """DFRobot DFR0440 left/right vibration motor driver configuration.

    Each DFR0440 input is treated as a PWM-capable logic control line. GP14 and
    GP15 are intentionally unused by the current camera/ToF/BNO wiring plan.
    """

    enabled: bool = _env_bool("ARIA_HAPTIC_ENABLED", True)
    left_pin: int = _env_int("ARIA_HAPTIC_LEFT_PIN", 14)
    right_pin: int = _env_int("ARIA_HAPTIC_RIGHT_PIN", 15)
    pwm_hz: int = _env_int("ARIA_HAPTIC_PWM_HZ", 200)
    active_high: bool = _env_bool("ARIA_HAPTIC_ACTIVE_HIGH", True)


def _env_role_ints(name: str, default: dict[str, int], *, base: int = 10) -> dict[str, int]:
    raw = os.environ.get(name)
    if not raw:
        return dict(default)
    values = dict(default)
    for item in raw.split(","):
        if not item.strip() or ":" not in item:
            continue
        role, value = item.split(":", 1)
        try:
            values[role.strip()] = int(value.strip(), base)
        except ValueError:
            continue
    return values


@dataclass(frozen=True)
class DetectorConfig:
    model_path: str | None = os.environ.get("ARIA_HEF_PATH")
    confidence_threshold: float = _env_float("ARIA_CONF_THRESHOLD", 0.35)
    input_size: int = _env_int("ARIA_DETECTOR_INPUT_SIZE", 640)
    quantized_input: bool = _env_bool("ARIA_DETECTOR_QUANTIZED", True)


@dataclass(frozen=True)
class UiConfig:
    box_persistence_s: float = _env_float("ARIA_BOX_PERSISTENCE_S", 0.45)
    jpeg_quality: int = _env_int("ARIA_JPEG_QUALITY", 45)
    stream_max_width: int = _env_int("ARIA_STREAM_MAX_WIDTH", 480)
    raw_stream_fps: float = _env_float("ARIA_RAW_STREAM_FPS", 2.0)
    detection_interval_s: float = _env_float("ARIA_DETECTION_INTERVAL_S", 0.0)
    backup_switch_after_s: float = _env_float("ARIA_BACKUP_SWITCH_AFTER_S", 1.5)
    main_recover_after_s: float = _env_float("ARIA_MAIN_RECOVER_AFTER_S", 3.0)
