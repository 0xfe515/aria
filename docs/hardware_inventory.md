# ARIA Hardware Inventory

Last verified: 2026-06-08 on `aria-core` (`aria@aria-core`).

## Current v1 working scope

ARIA currently targets a two-camera demo with **one** VL53L5CX ToF sensor. Do not require left/right ToF sensors for the current scope unless the project scope is explicitly changed.

The single ToF stream is a conservative center/global proximity signal. Left/right warning regions must be inferred from camera role, image-region geometry, object size/motion, and detector output; they are not independently measured side distances.

## Raspberry Pi target

- Host: `aria-core`
- SSH: `aria@aria-core`
- Repo path: `/home/aria/aria`
- Raspberry Pi: Raspberry Pi 5 8GB
- Accelerator: Raspberry Pi AI HAT with Hailo-8L
- Hailo status: `hailortcli fw-control identify` reports `Device Architecture: HAILO8L`, firmware `4.23.0`.
- Verified HEF model: `/home/aria/proto/prototype/models/yolov8n_640.hef`

## Cameras

| Role | Capture node | Device name | Verified capture | Notes |
| --- | --- | --- | --- | --- |
| Right | `/dev/video0` | Arducam OV9281 USB Camera | 1280x720, 3 frames, about 15.5 FPS in short check | `/dev/video1` is metadata |
| Left | `/dev/video2` | USB Camera | 640x480, 3 frames, about 10.3 FPS in short check | `/dev/video3` is metadata |

Use `scripts/verify_dual_camera.py` to verify both cameras simultaneously:

```bash
python3 scripts/verify_dual_camera.py \
  --host aria@aria-core \
  --remote-repo /home/aria/aria \
  --left-device /dev/video2 \
  --right-device /dev/video0 \
  --seconds 5 \
  --save-samples
```

## ToF distance sensor

- Sensor: 1x VL53L5CX 8x8-zone Time-of-Flight sensor.
- Current scope: use exactly one ToF sensor.
- Pico serial: `/dev/ttyACM0`
- Pico wiring:
  - VL53L5CX SDA -> Pico GP20
  - VL53L5CX SCL -> Pico GP21
- Pico frame format: existing `ARF1` binary frame parsed by `aria.distance`.
- Verification result: valid frames received with `valid_zones=64`.

Verification:

```bash
python3 scripts/verify_tof.py \
  --host aria@aria-core \
  --remote-repo /home/aria/aria \
  --port /dev/ttyACM0 \
  --seconds 2 \
  --min-bytes 1 \
  --require-frame
```

## IMU

- Expected/previously discussed module: BNO055-class IMU.
- Current status: **not detected** by non-destructive Pico I2C scan.
- Scan evidence from Pico:
  - I2C0 GP20/GP21 detected `[0x29]`, matching the VL53L5CX ToF sensor.
  - BNO055 expected address `0x28` was not detected.
  - Other common Pico I2C pin pairs scanned empty.
- Pico current ToF `main.py` backup before probing: `/home/aria/aria/.pico_backups/20260608_071606/main.py` on `aria-core`.

Before implementing IMU-dependent behavior, verify physical IMU installation, power, GND, SDA/SCL pins, and address-select state. If BNO055 is used on the same bus as ToF, prefer address `0x28` to avoid conflict with the ToF at `0x29`.

## Not in current scope

- Left/right additional VL53L5CX sensors.
- HC-SR04P ultrasonic glass/mirror detection.
- Haptic motor output hardware.
- Production-quality stereo depth or 3D mapping.
