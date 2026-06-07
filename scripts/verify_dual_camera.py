#!/usr/bin/env python3
"""Verify simultaneous left/right camera capture on the ARIA Raspberry Pi target.

Run this script from a development machine. By default it SSHes to
aria@aria-core and executes the dual-camera check there. Override with
ARIA_VERIFY_HOST or --host if needed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_HOST = os.environ.get("ARIA_VERIFY_HOST", "aria@aria-core")
DEFAULT_REMOTE_REPO = os.environ.get("ARIA_REMOTE_REPO", "/home/aria/aria")
DEFAULT_LEFT_DEVICE = os.environ.get("ARIA_LEFT_CAMERA", "/dev/video2")
DEFAULT_RIGHT_DEVICE = os.environ.get("ARIA_RIGHT_CAMERA", "/dev/video0")


def normalize_device(device: str) -> int | str:
    """Return an OpenCV VideoCapture source from a CLI device string."""
    return int(device) if device.isdigit() else device


def shape_to_list(shape: Any) -> list[int] | None:
    """Convert a frame.shape-like object to a JSON-friendly list."""
    if shape is None:
        return None
    if not isinstance(shape, tuple):
        return None
    try:
        return [int(part) for part in shape]
    except Exception:
        return None


@dataclass
class CameraStats:
    role: str
    device: str
    opened: bool = True
    frames: int = 0
    failures: int = 0
    shape: tuple[int, ...] | None = None
    first_timestamp_s: float | None = None
    last_timestamp_s: float | None = None

    def record_frame(self, shape: tuple[int, ...], timestamp_s: float) -> None:
        self.frames += 1
        self.shape = shape
        if self.first_timestamp_s is None:
            self.first_timestamp_s = timestamp_s
        self.last_timestamp_s = timestamp_s

    def record_failure(self) -> None:
        self.failures += 1

    def summary(self, start_s: float, end_s: float) -> dict[str, Any]:
        elapsed = max(end_s - start_s, 1e-6)
        return {
            "role": self.role,
            "device": self.device,
            "opened": self.opened,
            "frames": self.frames,
            "failures": self.failures,
            "shape": shape_to_list(self.shape),
            "fps": round(self.frames / elapsed, 1),
            "first_timestamp_s": self.first_timestamp_s,
            "last_timestamp_s": self.last_timestamp_s,
        }


def latest_timestamp_skew_ms(stats: dict[str, CameraStats]) -> float | None:
    timestamps = [camera.last_timestamp_s for camera in stats.values()]
    if any(timestamp is None for timestamp in timestamps):
        return None
    valid_timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    return round((max(valid_timestamps) - min(valid_timestamps)) * 1000.0, 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify simultaneous dual-camera capture on aria Pi target")
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH target, default: %(default)s")
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO, help="Repository path on target")
    parser.add_argument("--remote", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--left-device", default=DEFAULT_LEFT_DEVICE, help="Left camera index or /dev/video* path")
    parser.add_argument("--right-device", default=DEFAULT_RIGHT_DEVICE, help="Right camera index or /dev/video* path")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--seconds", type=float, default=5.0, help="Capture duration")
    parser.add_argument("--min-frames", type=int, default=5, help="Minimum frames required per camera")
    parser.add_argument("--save-samples", action="store_true", help="Save sample frames on the target")
    parser.add_argument("--sample-dir", default="/tmp/aria_camera_samples", help="Target directory for sample frames")
    parser.add_argument("--no-gui", action="store_true", help="Reserved for symmetry with verify_camera.py; no GUI is opened")
    return parser.parse_args()


def is_target_host(host: str) -> bool:
    target_user, _, target_name = host.partition("@")
    local_names = {socket.gethostname(), socket.getfqdn()}
    return getpass.getuser() == target_user and (target_name in local_names or target_name in {"localhost", "127.0.0.1"})


def rerun_on_target(args: argparse.Namespace) -> int:
    if args.remote or is_target_host(args.host):
        return run_dual_camera_check(args)

    forwarded = [
        "--remote",
        "--left-device",
        args.left_device,
        "--right-device",
        args.right_device,
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--seconds",
        str(args.seconds),
        "--min-frames",
        str(args.min_frames),
        "--sample-dir",
        args.sample_dir,
    ]
    if args.save_samples:
        forwarded.append("--save-samples")
    if args.no_gui:
        forwarded.append("--no-gui")

    remote_cmd = "cd {repo} && {py} scripts/verify_dual_camera.py {args}".format(
        repo=shlex.quote(args.remote_repo),
        py=shlex.quote(os.environ.get("ARIA_REMOTE_PYTHON", "python3")),
        args=" ".join(shlex.quote(part) for part in forwarded),
    )
    print(f"[local] running dual-camera verification on {args.host}: {remote_cmd}")
    return subprocess.call(["ssh", args.host, remote_cmd])


def _open_capture(cv2: Any, role: str, device: str, width: int, height: int) -> tuple[Any, CameraStats]:
    cap = cv2.VideoCapture(normalize_device(device))
    stats = CameraStats(role=role, device=device, opened=bool(cap.isOpened()))
    if stats.opened:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap, stats


def _save_sample(cv2: Any, frame: Any, sample_dir: Path, role: str, suffix: str) -> str | None:
    sample_dir.mkdir(parents=True, exist_ok=True)
    path = sample_dir / f"{role}_{suffix}.jpg"
    ok = cv2.imwrite(str(path), frame)
    return str(path) if ok else None


def run_dual_camera_check(args: argparse.Namespace) -> int:
    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover - target dependency check
        print(f"FAIL: OpenCV import failed: {exc}", file=sys.stderr)
        return 2

    video_nodes = sorted(str(path) for path in Path("/dev").glob("video*"))
    print(f"host={socket.gethostname()} user={getpass.getuser()}")
    print(f"video_nodes={video_nodes}")
    print(f"left_device={args.left_device} right_device={args.right_device}")

    captures: dict[str, Any] = {}
    stats: dict[str, CameraStats] = {}
    first_samples: dict[str, str] = {}
    last_samples: dict[str, str] = {}
    last_frames: dict[str, Any] = {}

    try:
        for role, device in (("left", args.left_device), ("right", args.right_device)):
            cap, camera_stats = _open_capture(cv2, role, device, args.width, args.height)
            captures[role] = cap
            stats[role] = camera_stats
            if not camera_stats.opened:
                print(f"FAIL: could not open {role} camera source {device!r}", file=sys.stderr)

        if not all(camera.opened for camera in stats.values()):
            print("SUMMARY_JSON=" + json.dumps({role: camera.summary(0.0, 1.0) for role, camera in stats.items()}, sort_keys=True))
            return 1

        sample_dir = Path(args.sample_dir)
        start_s = time.monotonic()
        deadline_s = start_s + max(args.seconds, 0.1)
        while time.monotonic() < deadline_s:
            for role, cap in captures.items():
                ok, frame = cap.read()
                now_s = time.monotonic()
                if not ok or frame is None:
                    stats[role].record_failure()
                    continue
                stats[role].record_frame(tuple(frame.shape), now_s)
                last_frames[role] = frame
                if args.save_samples and role not in first_samples:
                    saved = _save_sample(cv2, frame, sample_dir, role, "first")
                    if saved:
                        first_samples[role] = saved

        end_s = time.monotonic()
        if args.save_samples:
            for role, frame in last_frames.items():
                saved = _save_sample(cv2, frame, sample_dir, role, "last")
                if saved:
                    last_samples[role] = saved
    finally:
        for cap in captures.values():
            try:
                cap.release()
            except Exception:
                pass

    summary = {role: camera.summary(start_s, end_s) for role, camera in stats.items()}
    skew = latest_timestamp_skew_ms(stats)
    result = {
        "cameras": summary,
        "latest_timestamp_skew_ms": skew,
        "sample_files": {"first": first_samples, "last": last_samples},
    }
    print("SUMMARY_JSON=" + json.dumps(result, sort_keys=True))

    failed = [role for role, camera in stats.items() if camera.frames < args.min_frames]
    if failed:
        print(f"FAIL: insufficient frames for {failed}; min_frames={args.min_frames}", file=sys.stderr)
        return 1

    print(
        "PASS: dual cameras captured "
        f"left={stats['left'].frames} frames ({summary['left']['shape']}, {summary['left']['fps']} fps), "
        f"right={stats['right'].frames} frames ({summary['right']['shape']}, {summary['right']['fps']} fps), "
        f"latest_skew_ms={skew}"
    )
    if args.save_samples:
        print(f"sample_files={result['sample_files']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(rerun_on_target(parse_args()))
