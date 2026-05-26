---
name: aria-parallel-verification
description: ARIA project workflow for splitting work into narrow SubAgent tasks, reviewing their outputs, and running Raspberry Pi hardware verification through local scripts that SSH to aria@aira-core. Use when planning concurrent implementation, preparing SubAgent prompts, integrating SubAgent results, or verifying camera, Hailo, and ToF behavior for ARIA v0.
---

# ARIA Parallel Verification Skill

Use this skill in the ARIA repository when work needs to be split across SubAgents or when hardware checks must run on the Raspberry Pi target.

## Required Context

Before changing code, read:

- `AGENTS.md`
- Relevant source files for the module being changed
- Existing tests, if present

Follow the ARIA v0 scope in `AGENTS.md`: single main camera, Hailo-8L YOLOv8n, center VL53L5CX over Pico USB CDC, OpenCV GUI/text alerts.

## SubAgent Task Template

Create one focused task per SubAgent. Do not assign broad multi-module work.

```md
Purpose:
<one module or behavior only>

Input/Output:
- Input: <specific files, interfaces, data shape>
- Output: <specific expected artifact or behavior>

Files/directories allowed:
- <exact paths>

Forbidden changes:
- <paths or behaviors the SubAgent must not touch>

Constraints:
- Keep changes small and reviewable.
- Preserve hardware adapter boundaries.
- Do not commit generated caches, model files, secrets, or credentials.
- Do not treat CPU-only inference as v0 completion.

Validation:
- <pytest or script command>
- If hardware validation is required, use the local verification scripts below.

Required work log:
- Completed changes
- Files touched
- Commands run and results
- Known issues/blockers
- Next recommended step
```

## Recommended Parallel Work Split

Safe parallel lanes for ARIA v0:

- `camera`: OpenCV capture adapter and camera discovery only
- `distance`: Pico USB CDC frame parser and serial reader only
- `detector`: Hailo model loading/inference adapter only
- `fusion`: pure detection/ToF/risk logic plus pytest only
- `ui`: OpenCV overlay/status rendering only
- `alerts`: GUI/text alert adapter boundary only

Avoid assigning two SubAgents to edit the same file unless one finishes and is reviewed first.

## Integration Checklist

After receiving a SubAgent work log:

1. Run `git status --short`.
2. Review the diff for only allowed paths.
3. Run the specified validation command.
4. Run relevant import/static checks.
5. If hardware behavior changed, run the relevant verification script from the development machine.
6. If issues remain, send a narrow follow-up task instead of accepting broad fixes.

## Local-to-Pi Verification Commands

These scripts are launched locally but execute the actual checks on the Raspberry Pi over SSH. Default target is `aria@aira-core`.

```bash
python3 scripts/verify_camera.py
python3 scripts/verify_hailo.py --hef /path/on/pi/yolov8n.hef
python3 scripts/verify_tof.py --port /dev/ttyACM0
```

Overrides:

```bash
ARIA_VERIFY_HOST=aria@aria-core python3 scripts/verify_camera.py
ARIA_REMOTE_REPO=/path/to/aria python3 scripts/verify_hailo.py --skip-hef
```

If Pi access is unavailable, run local static checks only and report that hardware verification is blocked.

## Completion Rule

ARIA v0 is not complete until the acceptance checks in `AGENTS.md` pass on the Raspberry Pi target, including Hailo inference on Hailo hardware and live ToF data.
