#!/usr/bin/env python3
"""Run ARIA v0 with selectable Web and/or Qt UI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aria.config import CameraConfig, DetectorConfig, DualCameraConfig, TofConfig, UiConfig, _env_bool, _env_float, _env_int
from aria.ui import WebDemo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARIA v0 demo")
    web = parser.add_mutually_exclusive_group()
    web.add_argument("--web", dest="web", action="store_true", default=_env_bool("ARIA_WEB", True))
    web.add_argument("--no-web", dest="web", action="store_false")
    qt = parser.add_mutually_exclusive_group()
    qt.add_argument("--qt", dest="qt", action="store_true", default=_env_bool("ARIA_QT", False))
    qt.add_argument("--no-qt", dest="qt", action="store_false")
    parser.add_argument("--dual-camera", action="store_true", default=_env_bool("ARIA_DUAL_CAMERA", False))
    parser.add_argument("--primary-role", default=os.environ.get("ARIA_PRIMARY_CAMERA", "right"))
    parser.add_argument("--host", default=os.environ.get("ARIA_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--web-port", "--port", dest="port", type=int, default=_env_int("ARIA_WEB_PORT", 8080))
    parser.add_argument("--camera-source", default=os.environ.get("ARIA_CAMERA_SOURCE", "0"))
    parser.add_argument("--camera-width", type=int, default=_env_int("ARIA_CAMERA_WIDTH", 1280))
    parser.add_argument("--camera-height", type=int, default=_env_int("ARIA_CAMERA_HEIGHT", 720))
    parser.add_argument("--camera-fps", type=int, default=_env_int("ARIA_CAMERA_FPS", 30))
    parser.add_argument("--camera-threaded", action=argparse.BooleanOptionalAction, default=_env_bool("ARIA_CAMERA_THREADED", True))
    parser.add_argument("--tof-port", default=os.environ.get("ARIA_TOF_PORT"))
    parser.add_argument("--tof-baud", type=int, default=_env_int("ARIA_TOF_BAUD", 115200))
    parser.add_argument("--hef-path", default=os.environ.get("ARIA_HEF_PATH"))
    parser.add_argument("--conf-threshold", type=float, default=_env_float("ARIA_CONF_THRESHOLD", 0.35))
    parser.add_argument("--detector-input-size", type=int, default=_env_int("ARIA_DETECTOR_INPUT_SIZE", 640))
    parser.add_argument("--box-persistence-s", type=float, default=_env_float("ARIA_BOX_PERSISTENCE_S", 0.45))
    parser.add_argument("--jpeg-quality", type=int, default=_env_int("ARIA_JPEG_QUALITY", 45))
    parser.add_argument("--stream-max-width", type=int, default=_env_int("ARIA_STREAM_MAX_WIDTH", 480))
    parser.add_argument("--raw-stream-fps", type=float, default=_env_float("ARIA_RAW_STREAM_FPS", 2.0))
    parser.add_argument("--detection-interval-s", type=float, default=_env_float("ARIA_DETECTION_INTERVAL_S", 0.0))
    parser.add_argument("--web-fps", type=float, default=_env_float("ARIA_WEB_FPS", 30.0))
    return parser.parse_args()


def resolve_hef_path(path: str | None) -> str | None:
    """Resolve HEF model paths independent of the caller's current directory.

    Historically the demo was often launched from ``/home/aria`` with
    ``--hef-path proto/...`` while the repo itself lives at ``/home/aria/aria``.
    Newer invocations may launch from the repo root. Try both layouts so the
    old command lines keep working.
    """
    if not path:
        return None
    raw = Path(path).expanduser()
    if raw.is_absolute():
        return str(raw)

    candidates = [
        Path.cwd() / raw,
        REPO_ROOT / raw,
        REPO_ROOT.parent / raw,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return str(raw)


def build_pipeline(args: argparse.Namespace) -> WebDemo:
    hef_path = resolve_hef_path(args.hef_path)
    if args.dual_camera:
        dual_config = DualCameraConfig.from_env()
        # allow CLI override of primary role
        if args.primary_role != dual_config.primary_role:
            # frozen dataclass, replace
            from dataclasses import replace
            dual_config = replace(dual_config, primary_role=args.primary_role)
        return WebDemo(
            dual_camera_config=dual_config,
            tof_config=TofConfig(port=args.tof_port, baud=args.tof_baud),
            detector_config=DetectorConfig(
                model_path=hef_path,
                confidence_threshold=args.conf_threshold,
                input_size=args.detector_input_size,
            ),
            ui_config=UiConfig(
                box_persistence_s=args.box_persistence_s,
                jpeg_quality=args.jpeg_quality,
                stream_max_width=args.stream_max_width,
                raw_stream_fps=args.raw_stream_fps,
                detection_interval_s=args.detection_interval_s,
            ),
            host=args.host,
            port=args.port,
            stream_interval=1.0 / max(args.web_fps, 1.0),
            enable_web=args.web,
        )

    return WebDemo(
        camera_config=CameraConfig(
            source=args.camera_source,
            width=args.camera_width,
            height=args.camera_height,
            fps=args.camera_fps,
            threaded=args.camera_threaded,
        ),
        tof_config=TofConfig(port=args.tof_port, baud=args.tof_baud),
        detector_config=DetectorConfig(
            model_path=hef_path,
            confidence_threshold=args.conf_threshold,
            input_size=args.detector_input_size,
        ),
        ui_config=UiConfig(
            box_persistence_s=args.box_persistence_s,
            jpeg_quality=args.jpeg_quality,
            stream_max_width=args.stream_max_width,
            raw_stream_fps=args.raw_stream_fps,
            detection_interval_s=args.detection_interval_s,
        ),
        host=args.host,
        port=args.port,
        stream_interval=1.0 / max(args.web_fps, 1.0),
        enable_web=args.web,
    )


def main() -> int:
    args = parse_args()
    if not args.web and not args.qt:
        print("At least one UI must be enabled; use --web, --qt, or a wrapper script.", file=sys.stderr)
        return 2
    if not args.hef_path:
        print("Warning: --hef-path/ARIA_HEF_PATH is not set; detector will be marked not_loaded.", file=sys.stderr)
    if not args.tof_port:
        print("Warning: --tof-port/ARIA_TOF_PORT is not set; ToF will be unavailable.", file=sys.stderr)

    pipeline = build_pipeline(args)
    if args.qt:
        from aria.qt_ui import QtDemo
        return QtDemo(pipeline).run()

    pipeline.start()
    pipeline.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
