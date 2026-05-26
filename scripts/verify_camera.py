#!/usr/bin/env python3
"""Verify the ARIA main camera on the Raspberry Pi target.

Run this script from a development machine. By default it SSHes to
aria@aria-core and executes the camera check there. Override with
ARIA_VERIFY_HOST or --host if needed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_HOST = os.environ.get("ARIA_VERIFY_HOST", "aria@aria-core")
DEFAULT_REMOTE_REPO = os.environ.get("ARIA_REMOTE_REPO", "/home/aria/aria")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify camera capture on aria Pi target")
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH target, default: %(default)s")
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO, help="Repository path on target")
    parser.add_argument("--remote", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--device", default=None, help="Camera index or /dev/video* path")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--frames", type=int, default=60, help="Frames to capture before success")
    parser.add_argument("--no-gui", action="store_true", help="Do not open OpenCV window")
    return parser.parse_args()


def is_target_host(host: str) -> bool:
    target_user, _, target_name = host.partition("@")
    local_names = {socket.gethostname(), socket.getfqdn()}
    return getpass.getuser() == target_user and (target_name in local_names or target_name in {"localhost", "127.0.0.1"})


def rerun_on_target(args: argparse.Namespace) -> int:
    if args.remote or is_target_host(args.host):
        return run_camera_check(args)

    forwarded = ["--remote", "--width", str(args.width), "--height", str(args.height), "--frames", str(args.frames)]
    if args.device:
        forwarded += ["--device", args.device]
    if args.no_gui:
        forwarded.append("--no-gui")

    remote_cmd = "cd {repo} && {py} scripts/verify_camera.py {args}".format(
        repo=shlex.quote(args.remote_repo),
        py=shlex.quote(os.environ.get("ARIA_REMOTE_PYTHON", "python3")),
        args=" ".join(shlex.quote(part) for part in forwarded),
    )
    print(f"[local] running camera verification on {args.host}: {remote_cmd}")
    return subprocess.call(["ssh", args.host, remote_cmd])


def run_camera_check(args: argparse.Namespace) -> int:
    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover - target dependency check
        print(f"FAIL: OpenCV import failed: {exc}", file=sys.stderr)
        return 2

    video_nodes = sorted(str(path) for path in Path("/dev").glob("video*"))
    print(f"host={socket.gethostname()} user={getpass.getuser()}")
    print(f"video_nodes={video_nodes}")

    source: int | str = int(args.device) if args.device and args.device.isdigit() else (args.device or 0)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"FAIL: could not open camera source {source!r}", file=sys.stderr)
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    window = "ARIA camera verification"
    ok_frames = 0
    started = time.monotonic()
    last_shape = None
    try:
        while ok_frames < args.frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("FAIL: frame capture returned no image", file=sys.stderr)
                return 1
            ok_frames += 1
            last_shape = frame.shape
            cv2.putText(frame, f"ARIA camera verify frame={ok_frames}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            if not args.no_gui:
                cv2.imshow(window, frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    finally:
        cap.release()
        if not args.no_gui:
            cv2.destroyAllWindows()

    elapsed = max(time.monotonic() - started, 1e-6)
    print(f"PASS: captured {ok_frames} frames, shape={last_shape}, fps={ok_frames / elapsed:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(rerun_on_target(parse_args()))
