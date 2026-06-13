#!/usr/bin/env python3
"""Deprecated compatibility wrapper for the ARIA web demo.

Prefer ``scripts/run_demo.py --web --no-qt``. This wrapper delegates to the
canonical runner so CLI defaults, HEF path resolution, and dual-camera behavior
do not drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_demo import main as run_demo_main


def main() -> int:
    argv = sys.argv[1:]
    if "--web" not in argv and "--no-web" not in argv:
        argv = ["--web", *argv]
    if "--qt" not in argv and "--no-qt" not in argv:
        argv = ["--no-qt", *argv]
    original_argv = sys.argv
    try:
        sys.argv = [str(Path(__file__).with_name("run_demo.py")), *argv]
        return run_demo_main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
