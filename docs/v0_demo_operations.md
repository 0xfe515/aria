# ARIA v0 demo operation notes

## Run the demo

Preferred launchers:

```bash
# Remote browser UI
scripts/run_web_demo.sh

# Local desktop OpenCV window
scripts/run_opencv_demo.sh
```

`run_demo.sh` remains the common launcher behind both wrappers.

Useful environment variables, either exported or placed in `.env`:

```bash
ARIA_HEF_PATH=/home/aria/proto/prototype/models/yolov8n_640.hef
ARIA_TOF_PORT=/dev/ttyACM0
ARIA_CAMERA_SOURCE=0
ARIA_WEB_PORT=8080
ARIA_CAMERA_FPS=30
ARIA_CAMERA_FOURCC=MJPG
ARIA_CAMERA_BUFFER_SIZE=1
ARIA_CAMERA_THREADED=1
ARIA_BOX_PERSISTENCE_S=0.45
ARIA_STREAM_MAX_WIDTH=640
ARIA_JPEG_QUALITY=60
ARIA_WEB_FPS=30
```

UI selection:

```bash
# Web only, default for remote demos
scripts/run_web_demo.sh
# equivalent: scripts/run_demo.sh --web --no-qt --no-opencv

# Local HDMI/desktop OpenCV window only
scripts/run_opencv_demo.sh
# equivalent: scripts/run_demo.sh --no-web --no-qt --opencv

# Optional Qt window, if desired
scripts/run_demo.sh --no-web --qt --no-opencv
```

Qt requires either PySide6 or PyQt5 on the Raspberry Pi desktop environment. If
Qt is unavailable, use Web UI only.

## Desktop launcher

On `aria-core`:

```bash
cd /home/aria/aria
scripts/run_demo.sh --install-desktop-link
```

The script detects `/home/aria/Desktop` first and creates:

```text
/home/aria/Desktop/run_aria_web_demo.sh
/home/aria/Desktop/run_aria_opencv_demo.sh
/home/aria/Desktop/run_aria_demo.sh -> web demo
```

## Web UI latency tuning

The launcher now targets responsive 30 FPS demos by default:

- `ARIA_CAMERA_FPS=30`, `ARIA_CAMERA_FOURCC=MJPG`, `ARIA_CAMERA_BUFFER_SIZE=1`: request low-latency USB camera capture with minimal buffering.
- `ARIA_CAMERA_THREADED=1`: continuously drain the camera in a background thread and process the latest frame, reducing stale-frame lag when inference/web encoding is slower than capture.
- `ARIA_STREAM_MAX_WIDTH=640`: downscale the rendered web frame before JPEG encoding.
- `ARIA_JPEG_QUALITY=60`: smaller JPEGs reduce encode/network/browser latency.
- `ARIA_WEB_FPS=30`: stream at up to 30 FPS when camera/inference can keep up.

If the Pi/browser still feels delayed, reduce stream size first:

```bash
ARIA_STREAM_MAX_WIDTH=480 ARIA_JPEG_QUALITY=55 ARIA_WEB_FPS=30 scripts/run_demo.sh
```

For best visual quality at the cost of latency:

```bash
ARIA_STREAM_MAX_WIDTH=1280 ARIA_JPEG_QUALITY=85 ARIA_WEB_FPS=15 scripts/run_demo.sh
```

## Detection box persistence policy

`ARIA_BOX_PERSISTENCE_S` controls short UI-only detection holdover. The default
is `0.45` seconds: enough to reduce flicker from occasional missed Hailo frames,
but short enough that stale boxes do not linger. Matched detections update the
track every frame using class/label plus IoU, so boxes follow moving objects
instead of remaining fixed.

## Pico ToF firmware policy

For v0, use the MicroPython bridge in `firmware/pico_vl53l5cx/main.py`.
The C/C++ Pico SDK migration is intentionally not part of the v0 demo path.
Provision/update the Pico with `scripts/provision_pico_vl53l5cx.py` and verify
USB CDC binary frames with `scripts/verify_tof.py --require-frame`.

## Hardware verification

From the development machine:

```bash
python3 scripts/verify_camera.py --no-gui
python3 scripts/verify_hailo.py --hef /home/aria/proto/prototype/models/yolov8n_640.hef --run-inference
python3 scripts/verify_tof.py --port /dev/ttyACM0 --require-frame
```

If GUI validation is needed, `aria-core` has a desktop environment. Prefer a
remote screenshot of the Web UI or Qt window rather than relying only on terminal
logs.
