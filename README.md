# ARIA

Project ARIA | 2026 KNUT CS CapstoneDesign

ARIA is a Raspberry Pi 5 + Hailo-8L smart-glasses demo for obstacle detection and situational awareness.

## Current v0 hardware map

- Pi target: `aria@aria-core` (`100.99.8.124` over Tailscale)
- Main/right camera: `/dev/video0` Arducam OV9281 capture node
- Backup/left camera: `/dev/video2` USB camera capture node
- Metadata nodes: `/dev/video1`, `/dev/video3`
- ToF: one VL53L5CX 8x8 sensor via Pico USB CDC at `/dev/ttyACM0`
- Detector: YOLOv8n HEF for Hailo-8L, usually `/home/aria/proto/prototype/models/yolov8n_640.hef`

## Local development checks

Run from the repo root:

```bash
python3 -m pytest -q
python3 -m compileall -q aria scripts tests
```

`pyproject.toml` sets `pythonpath = ["."]`, so plain `pytest -q` should also work from the repo root.

## Hardware verification on aria-core

From the development machine:

```bash
ssh aria@aria-core 'cd /home/aria/aria && python3 scripts/verify_dual_camera.py --left-device /dev/video2 --right-device /dev/video0'
ssh aria@aria-core 'cd /home/aria/aria && python3 scripts/verify_tof.py --port /dev/ttyACM0 --require-frame'
ssh aria@aria-core 'cd /home/aria/aria && python3 scripts/verify_hailo.py --hef /home/aria/proto/prototype/models/yolov8n_640.hef --run-inference'
```

## Run the web demo

Preferred command on `aria-core`:

```bash
cd /home/aria/aria
python3 scripts/run_demo.py \
  --web --no-qt --dual-camera \
  --hef-path proto/prototype/models/yolov8n_640.hef \
  --tof-port /dev/ttyACM0
```

Legacy wrapper compatibility remains available:

```bash
python3 scripts/run_web_demo.py --dual-camera --hef-path proto/prototype/models/yolov8n_640.hef --tof-port /dev/ttyACM0
```

Useful smoke checks while the demo is running:

```bash
curl -s http://127.0.0.1:8080/status | python3 -m json.tool
```

MJPEG endpoints:

- `/stream/combined`: active foveated overlay stream
- `/stream/right`: physical right/main raw stream
- `/stream/left`: physical left/backup raw stream

## Dual-camera policy

- Default composite mode is `foveated`.
- Right/main camera stays the primary risk coordinate system by default.
- If the main camera frame quality degrades, active primary can fail over to the left/backup camera with hysteresis.
- Risk/fusion is computed in the active primary camera's raw coordinates; bbox coordinates are transformed only for display on the combined canvas.
- The secondary/peripheral camera provides visual context and backup/failover, not stereo depth.

## Known limitations

- IMU is not verified and should not be required by v0 behavior.
- Current scope uses exactly one VL53L5CX ToF sensor; do not assume left/center/right ToF fusion.
- Foveated crop ratio is a practical demo default and should be tuned with real captured frames if the physical camera alignment changes.
- Haptic/TTS outputs are future adapters; v0 alerts are web/GUI-visible.
