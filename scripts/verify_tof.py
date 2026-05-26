#!/usr/bin/env python3
"""Verify Pico USB CDC / VL53L5CX ToF serial data on the Raspberry Pi target.

Defaults to SSH execution on aria@aria-core. The script validates that the USB
serial device is present and bytes are received. With --require-frame it also
requires at least one valid ARIA binary VL53L5CX frame.
"""

from __future__ import annotations

import argparse
import getpass
import glob
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_HOST = os.environ.get("ARIA_VERIFY_HOST", "aria@aria-core")
DEFAULT_REMOTE_REPO = os.environ.get("ARIA_REMOTE_REPO", "/home/aria/aria")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify ToF USB CDC serial on aria Pi target")
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH target, default: %(default)s")
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO, help="Repository path on target")
    parser.add_argument("--remote", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", default=os.environ.get("ARIA_TOF_PORT"), help="Serial port on target, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=int(os.environ.get("ARIA_TOF_BAUD", "115200")))
    parser.add_argument("--seconds", type=float, default=5.0, help="Read duration")
    parser.add_argument("--min-bytes", type=int, default=16, help="Minimum bytes required for PASS")
    parser.add_argument("--require-frame", action="store_true", help="Require a valid ARIA binary ToF frame")
    return parser.parse_args()


def is_target_host(host: str) -> bool:
    target_user, _, target_name = host.partition("@")
    local_names = {socket.gethostname(), socket.getfqdn()}
    return getpass.getuser() == target_user and (target_name in local_names or target_name in {"localhost", "127.0.0.1"})


def rerun_on_target(args: argparse.Namespace) -> int:
    if args.remote or is_target_host(args.host):
        return run_tof_check(args)

    forwarded = ["--remote", "--baud", str(args.baud), "--seconds", str(args.seconds), "--min-bytes", str(args.min_bytes)]
    if args.port:
        forwarded += ["--port", args.port]
    if args.require_frame:
        forwarded.append("--require-frame")

    remote_cmd = "cd {repo} && {py} scripts/verify_tof.py {args}".format(
        repo=shlex.quote(args.remote_repo),
        py=shlex.quote(os.environ.get("ARIA_REMOTE_PYTHON", "python3")),
        args=" ".join(shlex.quote(part) for part in forwarded),
    )
    print(f"[local] running ToF verification on {args.host}: {remote_cmd}")
    return subprocess.call(["ssh", args.host, remote_cmd])


def auto_detect_port() -> str | None:
    candidates: list[str] = []
    for pattern in ("/dev/serial/by-id/*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        candidates.extend(glob.glob(pattern))
    candidates = sorted(dict.fromkeys(candidates))
    print(f"serial_candidates={candidates}")
    return candidates[0] if candidates else None


def parse_aria_frames(raw: bytes) -> list[object]:
    try:
        from aria.distance import BINARY_FRAME_SIZE, MAGIC, parse_binary_frame
    except Exception as exc:
        print(f"WARN: could not import ARIA frame parser: {exc}")
        return []

    frames: list[object] = []
    cursor = 0
    while True:
        start = raw.find(MAGIC, cursor)
        if start < 0 or start + BINARY_FRAME_SIZE > len(raw):
            break
        candidate = raw[start : start + BINARY_FRAME_SIZE]
        try:
            frames.append(parse_binary_frame(candidate))
            cursor = start + BINARY_FRAME_SIZE
        except ValueError:
            cursor = start + 1
    return frames


def run_tof_check(args: argparse.Namespace) -> int:
    try:
        import serial  # type: ignore
    except Exception as exc:  # pragma: no cover - target dependency check
        print(f"FAIL: pyserial import failed: {exc}", file=sys.stderr)
        print("Install on target with: python3 -m pip install pyserial", file=sys.stderr)
        return 2

    print(f"host={socket.gethostname()} user={getpass.getuser()}")
    port = args.port or auto_detect_port()
    if not port:
        print("FAIL: no serial port found. Connect Pico USB CDC or pass --port /dev/ttyACM0", file=sys.stderr)
        return 1
    if not Path(port).exists():
        print(f"FAIL: serial port does not exist: {port}", file=sys.stderr)
        return 1

    print(f"opening port={port} baud={args.baud} seconds={args.seconds}")
    total = 0
    raw = bytearray()
    chunks: list[bytes] = []
    deadline = time.monotonic() + args.seconds
    try:
        with serial.Serial(port, args.baud, timeout=0.25) as ser:
            ser.reset_input_buffer()
            while time.monotonic() < deadline:
                data = ser.read(256)
                if data:
                    total += len(data)
                    raw.extend(data)
                    if len(chunks) < 8:
                        chunks.append(data)
    except Exception as exc:
        print(f"FAIL: serial read failed: {exc}", file=sys.stderr)
        return 1

    print(f"received_bytes={total}")
    for idx, chunk in enumerate(chunks):
        text = chunk.decode("utf-8", errors="replace").replace("\r", "\\r").replace("\n", "\\n")
        print(f"sample[{idx}].hex={chunk[:64].hex(' ')}")
        print(f"sample[{idx}].text={text[:160]}")

    if total < args.min_bytes:
        print(f"FAIL: received {total} bytes, expected at least {args.min_bytes}", file=sys.stderr)
        return 1

    frames = parse_aria_frames(bytes(raw))
    if frames:
        latest = frames[-1]
        distances = getattr(latest, "distances_mm", ())
        valid_values = [value for value in distances if value is not None and value > 0]
        print(
            "aria_frames={count} latest_sequence={seq} latest_status={status} valid_zones={valid}".format(
                count=len(frames),
                seq=getattr(latest, "sequence", None),
                status=getattr(latest, "status", None),
                valid=len(valid_values),
            )
        )
        if valid_values:
            print(f"distance_mm_min={min(valid_values)} distance_mm_median_sample={valid_values[len(valid_values)//2]}")
    elif args.require_frame:
        print("FAIL: no valid ARIA binary ToF frame decoded", file=sys.stderr)
        return 1

    print("PASS: ToF/Pico serial data received")
    return 0


if __name__ == "__main__":
    raise SystemExit(rerun_on_target(parse_args()))
