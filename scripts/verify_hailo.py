#!/usr/bin/env python3
"""Verify Hailo runtime and YOLO HEF availability on the Raspberry Pi target.

The script defaults to running through SSH on aria@aira-core. Provide --hef or
ARIA_HEF_PATH for the Hailo-8L YOLOv8n model file to validate.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shlex
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT_HOST = os.environ.get("ARIA_VERIFY_HOST", "aria@aira-core")
DEFAULT_REMOTE_REPO = os.environ.get("ARIA_REMOTE_REPO", "~/aria")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Hailo runtime/model on aria Pi target")
    parser.add_argument("--host", default=DEFAULT_HOST, help="SSH target, default: %(default)s")
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO, help="Repository path on target")
    parser.add_argument("--remote", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--hef", default=os.environ.get("ARIA_HEF_PATH"), help="Path to Hailo-8L YOLOv8n .hef on target")
    parser.add_argument("--skip-hef", action="store_true", help="Only check runtime/device, not model file")
    return parser.parse_args()


def is_target_host(host: str) -> bool:
    target_user, _, target_name = host.partition("@")
    local_names = {socket.gethostname(), socket.getfqdn()}
    return getpass.getuser() == target_user and (target_name in local_names or target_name in {"localhost", "127.0.0.1"})


def rerun_on_target(args: argparse.Namespace) -> int:
    if args.remote or is_target_host(args.host):
        return run_hailo_check(args)

    forwarded = ["--remote"]
    if args.hef:
        forwarded += ["--hef", args.hef]
    if args.skip_hef:
        forwarded.append("--skip-hef")

    remote_cmd = "cd {repo} && {py} scripts/verify_hailo.py {args}".format(
        repo=shlex.quote(args.remote_repo),
        py=shlex.quote(os.environ.get("ARIA_REMOTE_PYTHON", "python3")),
        args=" ".join(shlex.quote(part) for part in forwarded),
    )
    print(f"[local] running Hailo verification on {args.host}: {remote_cmd}")
    return subprocess.call(["ssh", args.host, remote_cmd])


def run_command(command: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        return proc.returncode, proc.stdout.strip()
    except FileNotFoundError:
        return 127, f"command not found: {command[0]}"
    except subprocess.TimeoutExpired:
        return 124, "command timed out"


def run_hailo_check(args: argparse.Namespace) -> int:
    print(f"host={socket.gethostname()} user={getpass.getuser()}")

    failed = False
    for cmd in (["hailortcli", "fw-control", "identify"], ["hailortcli", "scan"]):
        code, output = run_command(cmd)
        print(f"$ {' '.join(cmd)}\n{output or '<no output>'}")
        if code != 0:
            failed = True
            print(f"FAIL: {' '.join(cmd)} exited {code}", file=sys.stderr)

    try:
        import hailo_platform as hailo  # type: ignore
        print(f"PASS: imported hailo_platform from {getattr(hailo, '__file__', '<unknown>')}")
    except Exception as exc:  # pragma: no cover - target dependency check
        print(f"FAIL: hailo_platform import failed: {exc}", file=sys.stderr)
        failed = True
        hailo = None  # type: ignore

    if args.skip_hef:
        return 1 if failed else 0

    if not args.hef:
        print("FAIL: provide --hef /path/to/yolov8n.hef or set ARIA_HEF_PATH", file=sys.stderr)
        return 1

    hef_path = Path(args.hef).expanduser()
    if not hef_path.exists():
        print(f"FAIL: HEF file not found on target: {hef_path}", file=sys.stderr)
        return 1
    if hef_path.suffix.lower() != ".hef":
        print(f"WARN: model path does not end with .hef: {hef_path}")

    if hailo is not None:
        try:
            hef = hailo.HEF(str(hef_path))
            network_groups = hef.get_network_group_names()
            print(f"PASS: loaded HEF metadata, network_groups={network_groups}")
            try:
                vstreams = hef.get_sorted_output_names()
                print(f"output_names={vstreams}")
            except Exception as exc:
                print(f"WARN: could not query HEF output names: {exc}")
        except Exception as exc:
            print(f"FAIL: could not load HEF with hailo_platform: {exc}", file=sys.stderr)
            failed = True

    if failed:
        print("FAIL: Hailo verification did not pass", file=sys.stderr)
        return 1
    print("PASS: Hailo runtime and HEF metadata check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(rerun_on_target(parse_args()))
