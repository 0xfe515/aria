# ARIA Camera Mapping

Last verified: 2026-06-08 on `aria-core`.

## Current mapping

| Physical role | Capture node | Metadata node | V4L2 device label |
| --- | --- | --- | --- |
| Right camera | `/dev/video0` | `/dev/video1` | `Arducam OV9281 USB Camera: Ardu` |
| Left camera | `/dev/video2` | `/dev/video3` | `USB Camera: USB Camera` |

Only use capture nodes for OpenCV frame capture. Metadata nodes are not camera image streams.

## Verification commands

List devices on the target:

```bash
ssh aria@aria-core 'v4l2-ctl --list-devices && ls -l /dev/video*'
```

Check each camera individually:

```bash
python3 scripts/verify_camera.py --host aria@aria-core --remote-repo /home/aria/aria --device /dev/video0 --frames 3 --no-gui
python3 scripts/verify_camera.py --host aria@aria-core --remote-repo /home/aria/aria --device /dev/video2 --frames 3 --no-gui
```

Check both cameras simultaneously:

```bash
python3 scripts/verify_dual_camera.py \
  --host aria@aria-core \
  --remote-repo /home/aria/aria \
  --left-device /dev/video2 \
  --right-device /dev/video0 \
  --seconds 5 \
  --save-samples
```

Sample frames are saved on `aria-core` under `/tmp/aria_camera_samples` when `--save-samples` is passed.

## Design guidance

- Treat the right camera as the default primary camera until the UI/config layer supports a runtime `primary_camera` choice.
- First dual-camera milestone is stable simultaneous capture and UI visibility, not stereo depth.
- Hailo YOLO should run on one configured primary camera first; run detection on both only after measuring performance.
- Side-specific warnings should combine camera role, per-image region, bbox growth/motion, and the single center/global ToF proximity signal.
