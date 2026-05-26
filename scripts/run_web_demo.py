#!/usr/bin/env python3
"""Run the ARIA v0 lightweight web demo.

Deprecated compatibility wrapper. Prefer ``scripts/run_demo.py --web --no-qt``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aria.config import CameraConfig, DetectorConfig, TofConfig, UiConfig
from aria.ui import WebDemo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARIA v0 web demo")
    parser.add_argument("--host", default=os.environ.get("ARIA_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARIA_WEB_PORT", "8080")))
    parser.add_argument("--camera-source", default=os.environ.get("ARIA_CAMERA_SOURCE", "0"))
    parser.add_argument("--camera-width", type=int, default=int(os.environ.get("ARIA_CAMERA_WIDTH", "1280")))
    parser.add_argument("--camera-height", type=int, default=int(os.environ.get("ARIA_CAMERA_HEIGHT", "720")))
    parser.add_argument("--tof-port", default=os.environ.get("ARIA_TOF_PORT"))
    parser.add_argument("--tof-baud", type=int, default=int(os.environ.get("ARIA_TOF_BAUD", "115200")))
    parser.add_argument("--hef-path", default=os.environ.get("ARIA_HEF_PATH"))
    parser.add_argument("--conf-threshold", type=float, default=float(os.environ.get("ARIA_CONF_THRESHOLD", "0.35")))
    parser.add_argument("--detector-input-size", type=int, default=int(os.environ.get("ARIA_DETECTOR_INPUT_SIZE", "640")))
    parser.add_argument("--box-persistence-s", type=float, default=float(os.environ.get("ARIA_BOX_PERSISTENCE_S", "0.45")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    camera_config = CameraConfig(
        source=args.camera_source,
        width=args.camera_width,
        height=args.camera_height,
    )
    tof_config = TofConfig(port=args.tof_port, baud=args.tof_baud)
    detector_config = DetectorConfig(
        model_path=args.hef_path,
        confidence_threshold=args.conf_threshold,
        input_size=args.detector_input_size,
    )
    demo = WebDemo(
        camera_config=camera_config,
        tof_config=tof_config,
        detector_config=detector_config,
        ui_config=UiConfig(box_persistence_s=args.box_persistence_s),
        host=args.host,
        port=args.port,
    )
    demo.start()
    demo.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
