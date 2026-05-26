#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export ARIA_CAMERA_SOURCE="${ARIA_CAMERA_SOURCE:-0}"
export ARIA_CAMERA_WIDTH="${ARIA_CAMERA_WIDTH:-1280}"
export ARIA_CAMERA_HEIGHT="${ARIA_CAMERA_HEIGHT:-720}"
export ARIA_WEB_HOST="${ARIA_WEB_HOST:-0.0.0.0}"
export ARIA_WEB_PORT="${ARIA_WEB_PORT:-8080}"
export ARIA_BOX_PERSISTENCE_S="${ARIA_BOX_PERSISTENCE_S:-0.45}"
export ARIA_JPEG_QUALITY="${ARIA_JPEG_QUALITY:-70}"
export ARIA_STREAM_MAX_WIDTH="${ARIA_STREAM_MAX_WIDTH:-960}"
export ARIA_WEB_FPS="${ARIA_WEB_FPS:-12}"

# Demo-friendly auto-detection for aria-core. Explicit environment variables or
# CLI flags still win, but a plain ./run_demo.sh should use the known local HEF
# and Pico MicroPython USB CDC port when they are present.
if [[ -z "${ARIA_HEF_PATH:-}" ]]; then
  for candidate in \
    /home/aria/proto/prototype/models/yolov8n_640.hef \
    /usr/share/hailo-models/yolov8s_h8l.hef \
    /usr/share/hailo-models/yolov6n_h8l.hef; do
    if [[ -f "$candidate" ]]; then
      export ARIA_HEF_PATH="$candidate"
      break
    fi
  done
fi

if [[ -z "${ARIA_TOF_PORT:-}" ]]; then
  for candidate in /dev/serial/by-id/*MicroPython* /dev/ttyACM0 /dev/ttyACM1; do
    if [[ -e "$candidate" ]]; then
      export ARIA_TOF_PORT="$candidate"
      break
    fi
  done
fi

if [[ "${1:-}" == "--install-desktop-link" ]]; then
  desktop_dir="${ARIA_DESKTOP_DIR:-}"
  if [[ -z "$desktop_dir" ]]; then
    if [[ -d "$HOME/Desktop" ]]; then
      desktop_dir="$HOME/Desktop"
    else
      desktop_dir="$HOME/desktop"
      mkdir -p "$desktop_dir"
    fi
  fi
  chmod +x "$REPO_ROOT/scripts/run_demo.sh"
  ln -sfn "$REPO_ROOT/scripts/run_demo.sh" "$desktop_dir/run_aria_demo.sh"
  echo "Installed desktop launcher: $desktop_dir/run_aria_demo.sh"
  exit 0
fi

echo "ARIA demo configuration:"
echo "  repo: $REPO_ROOT"
echo "  camera: ${ARIA_CAMERA_SOURCE} (${ARIA_CAMERA_WIDTH}x${ARIA_CAMERA_HEIGHT})"
echo "  hef: ${ARIA_HEF_PATH:-<not set>}"
echo "  tof: ${ARIA_TOF_PORT:-<not set>} @ ${ARIA_TOF_BAUD:-115200}"
echo "  web: ${ARIA_WEB_HOST}:${ARIA_WEB_PORT}"
echo "  box persistence: ${ARIA_BOX_PERSISTENCE_S}s"
echo "  stream: max_width=${ARIA_STREAM_MAX_WIDTH}px jpeg_quality=${ARIA_JPEG_QUALITY} fps=${ARIA_WEB_FPS}"

if [[ -z "${ARIA_HEF_PATH:-}" ]]; then
  echo "Warning: ARIA_HEF_PATH is not set; Hailo detector will not load." >&2
elif [[ ! -f "$ARIA_HEF_PATH" ]]; then
  echo "Warning: HEF model not found at ARIA_HEF_PATH=$ARIA_HEF_PATH" >&2
fi

if [[ -z "${ARIA_TOF_PORT:-}" ]]; then
  echo "Warning: ARIA_TOF_PORT is not set; ToF reader will be disabled." >&2
elif [[ ! -e "$ARIA_TOF_PORT" ]]; then
  echo "Warning: ToF serial port not found: $ARIA_TOF_PORT" >&2
fi

python3 scripts/run_demo.py "$@"
