# ARIA Agent Instructions

## Project
- Project name: ARIA
- Repository: https://github.com/0xfe515/aria.git
- Goal: smart glasses demo for obstacle detection and situational awareness for visually impaired users.
- Current priority: build a working v0 physical demo with the parts that are currently available.

## Operating Model
- GPT-level agent owns planning, orchestration, code review, integration, and final verification.
- Smaller SubAgents may be used for narrow implementation tasks only. Assume SubAgents can be lightweight local models, so instructions must be explicit.
- Do not give a SubAgent broad multi-module tasks. Assign one module or one behavior at a time.
- Every SubAgent task must include:
  - purpose
  - input and output
  - files or directories it may edit
  - constraints and forbidden changes
  - validation command or manual check
- GPT-level agent must review SubAgent output before integration. If issues remain, send a focused follow-up task rather than accepting broad changes.

## Hardware
Available or assumed for v0:
- Raspberry Pi 5 8GB
- Raspberry Pi AI HAT with Hailo-8L
- Arducam 120fps Global Shutter USB Camera Board B0332 as the main camera
- 1x VL53L5CX Time-of-Flight 8x8-zone distance sensor, used as the center ToF sensor
- Raspberry Pi Pico 2W is assumed available because the wiring plan references it. Verify this before implementing the ToF bridge.

Known Raspberry Pi Pico 2W pin mapping for the connected VL53L5CX:
- VL53L5CX SDA -> Pico GP20
- VL53L5CX SCL -> Pico GP21

Not available yet or not required for v0:
- Arducam 1080P Day/Night Vision USB camera module B0506
- HC-SR04P ultrasonic distance sensor
- BNO055 IMU
- Additional VL53L5CX sensors for left and right ToF coverage
- Haptic motor output hardware

## Required v0 Demo Scope
The v0 demo must use only currently available hardware and must run on the real Raspberry Pi environment.

Required behavior:
- Capture live frames from the main camera.
- Run YOLOv8n object detection through the Hailo-8L AI HAT.
- Read distance data from the center VL53L5CX ToF sensor.
- Fuse object detections with ToF distance data to estimate which detected object or screen region is close.
- Divide the image into left, center, and right warning regions.
- Compute a simple rule-based risk level from distance, region, object size change, and movement toward the center.
- Display the result with OpenCV:
  - original camera view
  - detection, distance, and risk overlay
  - text status panel or text overlay with sensor and alert state
- Produce GUI/text alerts for v0. TTS and haptic outputs are future adapters, not required v0 output.

Hailo acceleration is mandatory for v0 completion:
- The demo must load and run a Hailo-compatible YOLOv8n model, such as a HEF compiled for Hailo-8L.
- CPU-only YOLO inference is allowed only as a local development smoke test.
- CPU-only inference must not be treated as a completed v0 demo.

## Out of Scope for v0 / TODO
Keep these items visible in TODOs and architecture extension points, but do not make them required for v0.

- Dual-camera stereo or image stitching:
  - Add when the sub camera is available.
  - v0 must work with a single main camera.
- Three-ToF left/center/right fusion:
  - Add when all VL53L5CX sensors are available.
  - v0 uses one center sensor and may simulate left/right region distance from image geometry only if clearly labeled.
- 3D mapping:
  - Dropped from v0 because the IMU is not available.
  - Revisit after BNO055 or another IMU is installed.
- Signboard OCR:
  - Not v0 required.
  - First evaluate whether pretrained OCR can read sign text without project-specific model training.
  - Do not block the obstacle detection demo on OCR.
- Elevator button guidance:
  - Not v0 required.
  - Treat as a future feature that likely needs data collection, labeling, or a reliable pretrained detector.
  - Do not assume model training can be completed by an agent unless the dataset and acceptance criteria are provided.
- HC-SR04P glass/mirror detection:
  - Add when the ultrasonic sensor is available.
- Haptic and TTS alerts:
  - Keep an `alerts` adapter boundary so GUI alerts can later be replaced or augmented.
  - Do not require hardware vibration output for v0.

## Suggested Module Boundaries
When adding code, prefer clear modules with narrow responsibilities:
- `camera`: main camera discovery, configuration, and frame capture.
- `detector`: Hailo YOLOv8n model loading, preprocessing, inference, and postprocessing.
- `distance`: VL53L5CX sensor transport and 8x8 distance frame parsing.
- `fusion`: association between detections, image regions, ToF zones, and risk level.
- `ui`: OpenCV windows, overlays, status text, and keyboard controls.
- `alerts`: v0 GUI/text alerts with future TTS/haptic-compatible interfaces.

Keep hardware-specific code behind small adapters so missing v1 hardware does not break the v0 demo.

## Runtime and Verification
- Execute and validate real device behavior on the provided Raspberry Pi environment, not only on the local workstation.
- Target host: `aria-core` through Tailscale MagicDNS, or Tailnet IP `100.99.8.124`.
- Use git clone or git pull on the Pi to synchronize code for verification.
- Never commit SSH keys, Tailnet credentials, model licenses, or local secrets.
- If Pi access is unavailable, perform local static checks only and clearly report that hardware verification is blocked.
- The demo environment is GUI-capable, but resource constrained. Prefer OpenCV windows over a browser/web dashboard for v0.
- Do not introduce a web server or streaming dashboard unless the user explicitly requests it.

## Git Workflow
- Use git actively to make work traceable and easy to synchronize with the Raspberry Pi.
- Check `git status` before making changes and before handing work back.
- Prefer small, reviewable changes grouped by behavior or module.
- Use branches for implementation work. If no branch name is specified, prefer the `codex/` prefix.
- Use `git diff` to review changes before summarizing or committing.
- Do not revert, overwrite, or discard user changes unless explicitly instructed.
- Keep generated caches, local model files, credentials, and machine-specific configuration out of git.
- Synchronize to `aria-core` through git operations such as clone, fetch, pull, branch checkout, and commit transfer rather than manual file copying when practical.

## v0 Acceptance Checks
The v0 demo is complete only when these checks pass on `aria-core`:
- The main camera opens and displays live frames.
- The Hailo runtime loads the YOLOv8n model and inference runs on Hailo, not CPU-only.
- VL53L5CX 8x8 distance data is received and converted into a usable center distance or zone map.
- The OpenCV overlay shows class, confidence, bounding box, estimated distance, and risk label.
- The status text reports camera, detector, ToF, FPS, and alert state.
- Close objects, center-region hazards, and missing distance data each produce clear and safe status behavior.
- The GUI runs at a usable demo frame rate on Raspberry Pi 5.

## Coding Guidance
- Inspect the existing repository before adding structure. Follow existing style when it appears.
- Keep v0 code simple and demonstrable. Prefer explicit adapters and configuration over speculative abstractions.
- Add future TODOs at extension points, but do not implement placeholder hardware paths that cannot be tested.
- Use configuration for device paths, model paths, thresholds, and debug flags.
- When a product datasheet or protocol reference is needed, use the official manufacturer source. For copy or compatible modules, verify against the original product or chipset documentation whenever possible.
- Fail safely when hardware is missing: surface the missing component in status output instead of crashing without context.
- When adding tests, prioritize pure logic tests for fusion/risk calculation and lightweight smoke checks for module imports.
