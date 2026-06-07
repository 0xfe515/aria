# ARIA Agent Instructions

## Project
- Project name: ARIA
- Repository: https://github.com/0xfe515/aria.git
- Goal: smart glasses demo for obstacle detection and situational awareness for visually impaired users.
- Current priority: build a working v0 physical demo with the parts that are currently available.

## Operating Model
- GPT-level parent agent owns planning, orchestration, product/scope decisions, code review synthesis, integration, and final verification.
- Use `pi-subagents` as the standard delegation mechanism when helpful. The package provides focused child Pi sessions and builtin agents such as `scout`, `researcher`, `planner`, `worker`, `reviewer`, `context-builder`, `oracle`, and `delegate`.
- Prefer natural-language delegation or the `subagent(...)` tool. Before relying on a specific agent or saved chain, inspect availability with `subagent({ action: "list" })`; use `subagent({ action: "doctor" })` when setup, async runs, or intercom behavior looks wrong.
- The parent agent must know how to route a task to a subagent running a different model when model diversity is useful. For one-off runs, pass a per-run model override such as `subagent({ agent: "reviewer", task: "Review this diff", model: "anthropic/claude-sonnet-4", context: "fresh", async: true })`, or in slash-command form `/run reviewer[model=anthropic/claude-sonnet-4] "Review this diff" --bg`. For parallel reviews, set `model` per task when useful. Do not hard-code project-wide model choices in this file; use `.pi/settings.json` `subagents.agentOverrides` only when the user explicitly wants persistent project defaults.
- Use the right role for the job:
  - `scout`: quick local codebase reconnaissance before planning.
  - `researcher`: external docs/spec/model/hardware research with sources.
  - `context-builder`: stronger handoff context and meta-prompts for larger work.
  - `planner`: implementation plan only; it should not edit code.
  - `oracle`: forked second opinion for risky direction, assumptions, drift, or architecture decisions; advisory unless explicitly assigned the single writer role.
  - `worker`: implementation after the parent approves scope and direction.
  - `reviewer`: fresh-context review/validation of a plan, diff, or implementation.
- Default workflow for non-trivial implementation: clarify scope and validation contract -> gather context with `scout`/`context-builder` and `researcher` when external facts matter -> plan when useful -> one async `worker` implements -> fresh-context parallel `reviewer`/validator passes -> parent synthesizes findings -> one async `worker` applies accepted fixes -> parent inspects diff and validates.
- Prefer `async: true` for subagent runs so the parent can continue independent inspection, validation prep, or synthesis. If no useful independent work remains, stop and wait for the async completion instead of polling.
- Keep writes single-threaded by default. Do not run multiple writer subagents against the same active worktree. Use parallel subagents for read-only scouting, research, review, and validation. Use `worktree: true` only for intentionally isolated parallel writer experiments and only from a clean git state.
- Use `context: "fresh"` for adversarial reviewers and validators so they inspect the repo/diff directly. Use forked context for `oracle` or approved `worker` runs when inherited parent context is useful; note that packaged `planner`, `worker`, and `oracle` may default to forked context.
- Do not let child subagents become orchestrators. Ordinary children must not launch their own subagents, run review loops, or make product/scope decisions. If a child needs an unapproved decision, it must escalate to the parent (via intercom/contact-supervisor when available) instead of guessing.
- SubAgent tasks must stay narrow. Assign one module, behavior, review angle, or research question at a time; do not give a child broad multi-module ownership unless it is explicitly a read-only reconnaissance/planning pass.
- Every implementation SubAgent task must include:
  - purpose and approved scope
  - input context, plan path/summary, and expected output
  - files or directories it may edit
  - constraints, non-goals, and forbidden changes
  - validation contract: commands to run or manual checks to perform, plus expected evidence
  - stop/escalation rules for missing hardware, unapproved decisions, or unsafe assumptions
- Review-only SubAgent tasks must explicitly say whether project/source files may be modified. For normal review fanout, say "do not modify project/source files"; returning findings through the response or configured output artifact is allowed.
- For large subagent outputs, configure an `output` path and `outputMode: "file-only"`; do not use `output: false` when a saved artifact is expected.
- At the end of each implementation or validation SubAgent task, require a concise work log so the next agent can resume if the task stops because of quota limits or an unknown interruption.
- The SubAgent work log must include:
  - completed changes or findings
  - files touched
  - commands run and their results/exit codes
  - validation evidence and hardware verification status
  - known issues or blockers
  - decisions needing parent/user approval
  - next recommended step
- GPT-level parent agent must review SubAgent output before integration or final summary. If issues remain, synthesize accepted fixes and send a focused follow-up task rather than accepting broad changes.

## Context Management

- Use `context-mode` for any command or file operation that may return large output.
- Prefer `ctx_execute`, `ctx_execute_file`, `ctx_batch_execute`, `ctx_fetch_and_index`, and `ctx_search` when analyzing, filtering, summarizing, parsing, testing, building, reading logs, inspecting git history, fetching docs, or processing API responses.
- Use normal `read` only when exact file contents are needed for editing; use `ctx_execute_file` for analysis-only reads.
- Use normal `bash` mainly for guaranteed-small output or state-changing operations such as `pwd`, small-directory `ls`, `mkdir`, `mv`, `rm`, `git add`, `git commit`, `git push`, package installs, and process control.
- Think in code: when deriving information from data, write a short script and print only the derived answer instead of dumping raw output into context.
- For web documentation, use `ctx_fetch_and_index` followed by `ctx_search`; do not use raw `curl`/`wget` output.
- Batch related searches or command captures in one call when practical.
- After resume or compact, search context-mode memory before asking the user to repeat prior decisions.
- Utility commands:
  - `ctx stats`: show context savings.
  - `ctx doctor`: diagnose context-mode.
  - `ctx upgrade`: update context-mode.
  - `ctx purge`: destructive reset of the knowledge base; only use when explicitly requested.

## Hardware
Available or assumed for the current demo scope:
- Raspberry Pi 5 8GB
- Raspberry Pi AI HAT with Hailo-8L
- Two USB cameras on the glasses:
  - `/dev/video0`: right camera, Arducam OV9281 capture node (`/dev/video1` is metadata)
  - `/dev/video2`: left camera, USB Camera capture node (`/dev/video3` is metadata)
- Exactly 1x VL53L5CX Time-of-Flight 8x8-zone distance sensor for the current scope. Treat it as a center/global proximity signal; do not require left/right ToF sensors unless the user explicitly changes scope.
- Raspberry Pi Pico 2W is present and currently streams the VL53L5CX data over USB CDC at `/dev/ttyACM0`.

Known Raspberry Pi Pico 2W pin mapping for the connected VL53L5CX:
- VL53L5CX SDA -> Pico GP20
- VL53L5CX SCL -> Pico GP21

Current IMU status:
- IMU is not detected yet. A non-destructive Pico I2C scan found the ToF at `0x29` on GP20/GP21 and no BNO055-style `0x28` address on common Pico I2C pin pairs.
- Do not implement IMU-dependent behavior until physical installation, wiring, and address selection are verified.

Pico-to-Pi distance bridge for v0:
- Manage the Pico-side VL53L5CX reader firmware in this repository, preferably under `firmware/pico_vl53l5cx/`.
- Use USB CDC serial as the default transport between Raspberry Pi Pico 2W and Raspberry Pi 5.
- The Pi-side `distance` module should read and decode the USB CDC serial stream.
- Consider a compact binary frame format for ToF data instead of defaulting to debug text. The format should carry at least timestamp or sequence number, sensor status, and the VL53L5CX 8x8 distance values.
- If a text mode is added, treat it as a debug mode and keep the binary-capable parser path available.

Not available yet or not required for current scope:
- HC-SR04P ultrasonic distance sensor
- Working/verified BNO055 IMU
- Additional VL53L5CX sensors for left and right ToF coverage; current scope intentionally uses only one ToF sensor.
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
- Display the result in a demo webpage for easier remote viewing:
  - original camera view
  - detection, distance, and risk overlay
  - text status panel or text overlay with sensor and alert state
  - browser-visible GUI/text alerts for v0
- OpenCV may still be used for camera capture and overlay rendering, but the primary demo UI should be served as a lightweight local web page. TTS and haptic outputs are future adapters, not required v0 output.

Hailo acceleration is mandatory for v0 completion:
- The demo must load and run a Hailo-compatible YOLOv8n model, such as a HEF compiled for Hailo-8L.
- CPU-only YOLO inference is allowed only as a local development smoke test.
- CPU-only inference must not be treated as a completed v0 demo.

Required v0 runtime components:
- HailoRT installed and working on the Raspberry Pi 5.
- Hailo Python bindings or an official Hailo example pipeline that can be integrated from Python.
- A Hailo-8L-compatible YOLOv8n `.hef` model.
- OpenCV for camera capture and overlay rendering.
- A lightweight browser-accessible demo UI for remote verification on the Raspberry Pi target.

Model asset policy:
- Do not commit large model files, downloaded datasets, or generated model artifacts unless the user explicitly asks for that.
- Keep model paths configurable.
- If a pretrained model is needed and is not already available on `aria-core`, search the internet for a suitable model, verify source and license, download it, and record the source URL, model name, version, and local path in the work log.
- Prefer official Hailo model zoo, vendor examples, or reputable upstream model releases when choosing pretrained assets.

## Out of Scope for v0 / TODO
Keep these items visible in TODOs and architecture extension points, but do not make them required for v0.

- Dual-camera stereo or image stitching:
  - Add when the sub camera is available.
  - v0 must work with a single main camera.
- Multi-ToF left/center/right fusion:
  - Not required for current scope; use exactly one VL53L5CX until the user explicitly changes this.
  - Current logic may simulate left/right warning regions from image geometry and object motion only if clearly labeled; do not claim independent side distance measurements.
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
- `ui`: lightweight webpage/web dashboard for remote viewing, with OpenCV-compatible overlay rendering and status text.
- `alerts`: v0 GUI/text alerts with future TTS/haptic-compatible interfaces.

Keep hardware-specific code behind small adapters so missing v1 hardware does not break the v0 demo.

## Runtime and Verification
- Execute and validate real device behavior on the provided Raspberry Pi environment, not only on the local workstation.
- Target host: `aria-core` through Tailscale MagicDNS, or Tailnet IP `100.99.8.124`.
- Target host SSH account name: `aria`.
- Use git clone or git pull on the Pi to synchronize code for verification.
- Never commit SSH keys, Tailnet credentials, model licenses, or local secrets.
- If Pi access is unavailable, perform local static checks only and clearly report that hardware verification is blocked.
- The demo environment is resource constrained, but remote viewing is important for demos. Prefer a lightweight local web page over an OpenCV-only window for v0.
- If adding a web server or streaming dashboard, keep it simple, local-network oriented, and suitable for Raspberry Pi 5 resource limits; avoid heavy browser frameworks unless explicitly requested.
- Provide and use small local verification scripts as implementation proceeds. These scripts should be launched from the development machine and must run the actual hardware checks on the Raspberry Pi via SSH as `aria@aria-core` by default, with `ARIA_VERIFY_HOST`, `--host`, or the Tailnet IP available as overrides:
  - `scripts/verify_camera.py` for camera discovery and frame display.
  - `scripts/verify_hailo.py` for Hailo runtime/model loading and inference path checks.
  - `scripts/verify_tof.py` for Pico USB CDC serial and VL53L5CX frame decoding.
- Use `pytest` as a required development tool for pure logic tests, especially `fusion` and `risk` calculations.
- Treat `ruff` or other format/static-analysis tools as recommended unless the repository later standardizes them.

## Git Workflow
- Use git actively to make work traceable and easy to synchronize with the Raspberry Pi.
- Check `git status` before making changes and before handing work back.
- Prefer small, reviewable changes grouped by behavior or module.
- Use branches for implementation work. If no branch name is specified, prefer the `codex/` prefix.
- Use `git diff` to review changes before summarizing or committing.
- Do not revert, overwrite, or discard user changes unless explicitly instructed.
- Keep generated caches, local model files, credentials, and machine-specific configuration out of git.
- At the end of completed work, commit reviewable changes and push the working branch to GitHub automatically unless the user explicitly says not to push.
- Synchronize to `aria-core` through git operations such as clone, fetch, pull, branch checkout, and commit transfer rather than manual file copying when practical.

## v0 Acceptance Checks
The v0 demo is complete only when these checks pass on `aria-core`:
- The main camera opens and displays live frames.
- The Hailo runtime loads the YOLOv8n model and inference runs on Hailo, not CPU-only.
- VL53L5CX 8x8 distance data is received and converted into a usable center distance or zone map.
- The webpage overlay shows class, confidence, bounding box, estimated distance, and risk label.
- The status text reports camera, detector, ToF, FPS, and alert state.
- Close objects, center-region hazards, and missing distance data each produce clear and safe status behavior.
- The web demo UI runs at a usable demo frame rate on Raspberry Pi 5 and is reachable from the remote development machine or Tailnet.

## Coding Guidance
- Inspect the existing repository before adding structure. Follow existing style when it appears.
- Keep v0 code simple and demonstrable. Prefer explicit adapters and configuration over speculative abstractions.
- Add future TODOs at extension points, but do not implement placeholder hardware paths that cannot be tested.
- Use configuration for device paths, model paths, thresholds, and debug flags.
- When a product datasheet or protocol reference is needed, use the official manufacturer source. For copy or compatible modules, verify against the original product or chipset documentation whenever possible.
- Fail safely when hardware is missing: surface the missing component in status output instead of crashing without context.
- When adding tests, prioritize pure logic tests for fusion/risk calculation and lightweight smoke checks for module imports.
