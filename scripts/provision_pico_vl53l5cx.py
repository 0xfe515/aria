#!/usr/bin/env python3
"""Provision the Pico 2W VL53L5CX MicroPython bridge on aria-core.

Run from the development machine. The script SSHes to the Raspberry Pi target,
installs user-space MicroPython tools, flashes official MicroPython for Pico 2W
when the board is in UF2 bootloader mode, uploads the mp-extras/vl53l5cx driver,
applies the RP2 large-I2C-write stability patch, and copies
firmware/pico_vl53l5cx/main.py to the Pico.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

DEFAULT_HOST = os.environ.get("ARIA_VERIFY_HOST", "aria@aria-core")
DEFAULT_REMOTE_REPO = os.environ.get("ARIA_REMOTE_REPO", "/home/aria/aria")
MICROPYTHON_UF2_URL = "https://micropython.org/resources/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2"
MP_EXTRAS_REPO = "https://github.com/mp-extras/vl53l5cx.git"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision ARIA Pico 2W VL53L5CX bridge")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO)
    parser.add_argument("--port", default=os.environ.get("ARIA_TOF_PORT", "/dev/ttyACM0"))
    parser.add_argument("--skip-flash", action="store_true", help="Do not flash MicroPython UF2")
    return parser.parse_args()


def run(cmd: list[str]) -> int:
    print("$", " ".join(shlex.quote(part) for part in cmd))
    return subprocess.call(cmd)


def main() -> int:
    args = parse_args()
    local_main = Path("firmware/pico_vl53l5cx/main.py")
    if not local_main.exists():
        print(f"missing {local_main}; run from repository root", file=sys.stderr)
        return 2

    remote_main = "/tmp/aria_pico_vl53l5cx_main.py"
    code = run(["scp", str(local_main), f"{args.host}:{remote_main}"])
    if code != 0:
        return code

    remote_script = f"""
set -eu
PORT={shlex.quote(args.port)}
REPO={shlex.quote(args.remote_repo)}
UF2_URL={shlex.quote(MICROPYTHON_UF2_URL)}
MP_REPO={shlex.quote(MP_EXTRAS_REPO)}
MP=/home/aria/.local/bin/mpremote
python3 -m pip install --user --break-system-packages mpremote pyserial
export PATH=/home/aria/.local/bin:$PATH
mkdir -p /home/aria/Downloads

if [ {str(args.skip_flash).lower()} = false ]; then
  if ! $MP connect "$PORT" exec "import sys; print(sys.implementation)" >/tmp/aria_mp_probe.txt 2>&1; then
    python3 - <<'PY'
import serial, time
try:
    ser = serial.Serial('/dev/ttyACM0', 1200, timeout=0.1)
    ser.dtr = False
    ser.rts = False
    time.sleep(0.2)
    ser.close()
except Exception as exc:
    print(f'1200-baud bootloader request: {{exc}}')
PY
    sleep 2
  fi
  if lsblk -o LABEL,MOUNTPOINT | grep -q RP2350; then
    cd /home/aria/Downloads
    UF2=$(basename "$UF2_URL")
    [ -f "$UF2" ] || wget -O "$UF2" "$UF2_URL"
    MOUNT=$(lsblk -nr -o LABEL,MOUNTPOINT | awk '$1=="RP2350" {{print $2; exit}}')
    cp "$UF2" "$MOUNT/"
    sync
    sleep 4
  fi
fi

cd /home/aria/Downloads
if [ ! -d vl53l5cx ]; then
  git clone --depth 1 "$MP_REPO" vl53l5cx
else
  git -C vl53l5cx pull --ff-only || true
fi
python3 - <<'PY'
from pathlib import Path
p = Path('/home/aria/Downloads/vl53l5cx/vl53l5cx/mp.py')
s = p.read_text()
old = '''    def _wr_multi(self, reg16, buf):
        self.i2c.writeto_mem(self.addr, reg16, buf, addrsize=16)
'''
new = '''    def _wr_multi(self, reg16, buf):
        # ARIA: chunk large firmware writes for RP2 MicroPython I2C stability.
        for off in range(0, len(buf), 128):
            self.i2c.writeto_mem(self.addr, reg16 + off, buf[off:off + 128], addrsize=16)
'''
if old in s:
    p.write_text(s.replace(old, new))
elif 'ARIA: chunk large firmware writes' not in s:
    raise SystemExit('unexpected mp.py _wr_multi implementation')
PY
$MP connect "$PORT" fs mkdir :lib 2>/dev/null || true
$MP connect "$PORT" fs mkdir :lib/vl53l5cx 2>/dev/null || true
for f in __init__.py _config_file.py _config_bytes.py mp.py vl_fw_config.bin; do
  $MP connect "$PORT" fs cp "/home/aria/Downloads/vl53l5cx/vl53l5cx/$f" ":lib/vl53l5cx/$f"
done
$MP connect "$PORT" fs cp {remote_main} :main.py
$MP connect "$PORT" reset || true
sleep 2
cd "$REPO"
python3 scripts/verify_tof.py --remote --port "$PORT" --seconds 5 --min-bytes 142 --require-frame
"""
    return run(["ssh", args.host, remote_script])


if __name__ == "__main__":
    raise SystemExit(main())
