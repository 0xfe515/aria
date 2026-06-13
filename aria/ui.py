"""Lightweight browser UI for ARIA v0.

Uses Python stdlib ``http.server`` to serve an HTML dashboard with MJPEG
streams and a JSON status endpoint. Supports both single-camera and dual-camera
modes. OpenCV overlays are drawn when available.
Missing cv2, camera, or serial produce clear status messages instead of crashes.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, cast
from urllib.parse import urlparse

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

from aria.camera import Camera, CameraConfig, CameraFrame, MultiCamera
from aria.config import DetectorConfig, DualCameraConfig, TofConfig, UiConfig
from aria.distance import BINARY_FRAME_SIZE, MAGIC, MULTI_MAGIC, parse_any_binary_frame
from aria.fusion import Region, TofFrame, TofFrameSet, fuse_detection, score_risk
from aria.quality import CameraQuality, assess_frame_quality
from aria.tracker import DetectionPersistence


@dataclass
class DemoStatus:
    camera: str = "not_initialized"
    fps: float = 0.0
    update_ms: float = 0.0
    frame_count: int = 0
    detection_count: int = 0
    detector: str = "not_initialized"
    detector_fps: float = 0.0
    detector_ms: float = 0.0
    tof_port: str | None = None
    tof_sequence: int | None = None
    tof_status: int | None = None
    tof_valid_zones: int = 0
    tof_center_mm: int | None = None
    tof_left_mm: int | None = None
    tof_right_mm: int | None = None
    tof_sensor_count: int = 0
    tof_roles: list[str] = field(default_factory=list)
    alert: str = "none"
    risk: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    # dual-camera additions
    dual_mode: bool = False
    primary_role: str = "right"
    active_primary_role: str = "right"
    backup_active: bool = False
    main_role: str = "right"
    backup_role: str | None = None
    main_quality: dict[str, Any] = field(default_factory=dict)
    backup_quality: dict[str, Any] = field(default_factory=dict)
    cameras: dict[str, Any] = field(default_factory=dict)
    imu_status: str = "not_configured"
    imu_heading_deg: float | None = None
    imu_roll_deg: float | None = None
    imu_pitch_deg: float | None = None
    imu_accel: list[float] | None = None
    imu_gyro: list[float] | None = None
    imu_calibration: Any = None


class _SharedState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: dict[str, bytes] = {
            "primary": b"",
            "secondary": b"",
            "left": b"",
            "right": b"",
            "combined": b"",
        }
        self._status = DemoStatus()

    def update(
        self,
        jpeg: dict[str, bytes] | bytes | None = None,
        status: DemoStatus | None = None,
    ) -> None:
        with self._lock:
            if jpeg is not None:
                if isinstance(jpeg, dict):
                    self._jpeg.update(jpeg)
                else:
                    self._jpeg["primary"] = jpeg
            if status is not None:
                self._status = status

    def get(self) -> tuple[bytes, DemoStatus]:
        """Backward-compatible single-camera getter. Returns primary JPEG."""
        with self._lock:
            return self._jpeg.get("primary", b"")[:], self._status

    def get_jpeg(self, role: str = "primary") -> bytes:
        with self._lock:
            return self._jpeg.get(role, b"")[:]

    def get_status(self) -> DemoStatus:
        with self._lock:
            return self._status


class OverlayRenderer:
    def __init__(self, font_scale: float = 0.55, thickness: int = 2) -> None:
        self.font_scale = font_scale
        self.thickness = thickness

    def render(self, image: Any, status: DemoStatus, detections: list[Any] | None = None) -> Any:
        if cv2 is None or image is None:
            return image
        h, w = image.shape[:2]
        self._draw_text(image, f"CAM: {status.camera}  FPS:{status.fps:.1f}  DET:{status.detection_count}", (10, 30))
        self._draw_text(
            image,
            f"ToF: seq={status.tof_sequence} zones={status.tof_valid_zones} center={status.tof_center_mm}mm",
            (10, 55),
        )
        self._draw_text(image, f"ALERT: {status.alert}", (10, 80))
        if status.dual_mode:
            backup_txt = " backup" if status.backup_active else " main"
            main_q = status.main_quality.get("status", "unknown") if status.main_quality else "unknown"
            self._draw_text(
                image,
                f"PRIMARY: {status.active_primary_role}{backup_txt}  MAIN({status.main_role}): {main_q}",
                (10, 105),
            )
        cv2.line(image, (w // 3, 0), (w // 3, h), (0, 255, 255), 1)
        cv2.line(image, (2 * w // 3, 0), (2 * w // 3, h), (0, 255, 255), 1)
        if detections:
            for det in detections:
                if not hasattr(det, "bbox"):
                    continue
                try:
                    if isinstance(det.bbox, tuple):
                        x1, y1, x2, y2 = det.bbox
                    else:
                        x1, y1, x2, y2 = det.bbox
                    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                    stale = bool(getattr(det, "stale", False))
                    risk = getattr(det, "risk", None)
                    risk_text = str(getattr(risk, "value", risk or ""))
                    distance_mm = getattr(det, "distance_mm", None)
                    color = (0, 165, 255) if stale else self._risk_color(risk_text)
                    cv2.rectangle(image, (x1, y1), (x2, y2), color, 1 if stale else 2)
                    label = getattr(det, "label", "obj")
                    conf = getattr(det, "confidence", 0.0)
                    suffix = " hold" if stale else ""
                    dist = f" {distance_mm}mm" if distance_mm is not None else ""
                    risk_txt = f" {risk_text}" if risk_text else ""
                    txt = f"{label} {conf:.2f}{dist}{risk_txt}{suffix}"
                    ty = max(y1 - 5, 15)
                    self._draw_text(image, txt, (x1, ty), color=color)
                except Exception:
                    pass
        return image

    def _risk_color(self, risk: str) -> tuple[int, int, int]:
        if "danger" in risk:
            return (0, 0, 255)
        if "caution" in risk:
            return (0, 255, 255)
        if "clear" in risk:
            return (0, 255, 0)
        return (255, 255, 255)

    def _draw_text(self, image: Any, text: str, org: tuple[int, int], color: tuple[int, int, int] = (0, 255, 0)) -> None:
        if cv2 is None:
            return
        cv2.putText(
            image, text, org, cv2.FONT_HERSHEY_SIMPLEX, self.font_scale, (0, 0, 0), self.thickness + 2
        )
        cv2.putText(
            image, text, org, cv2.FONT_HERSHEY_SIMPLEX, self.font_scale, color, self.thickness
        )


def _encode_jpeg(image: Any, quality: int = 70) -> bytes | None:
    if cv2 is None or image is None:
        return None
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else None


HTML_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ARIA v0 Demo</title>
<style>
*{box-sizing:border-box}
html,body{height:100%;width:100%}
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0b0f12;color:#e7f8ee;margin:0;padding:0;overflow:hidden}
.debug-dashboard{height:100vh;width:100vw;display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:8px;padding:8px;background:#0b0f12;overflow:hidden}
.video-stack{min-width:0;min-height:0;display:grid;grid-template-rows:minmax(0,2fr) minmax(0,1fr);gap:8px;overflow:hidden}
.stream-box,.status-sidebar{background:#151b20;border:1px solid #27333a;border-radius:8px;min-width:0;min-height:0;box-shadow:0 0 0 1px rgba(0,0,0,.25) inset;overflow:hidden}
.stream-box{display:flex;flex-direction:column;position:relative}
.stream-box h3{margin:0;padding:6px 8px;font-size:.78rem;line-height:1;background:#1d262d;color:#b8ffd2;border-bottom:1px solid #27333a;letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stream-box img{width:100%;height:100%;min-height:0;object-fit:contain;display:block;background:#000;flex:1;border:0}
.combined-panel h3{font-size:.86rem;color:#d5ffe4}
.raw-grid{min-width:0;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;overflow:hidden}
.raw-panel{height:100%}
.raw-grid>.left-panel{grid-column:1}
.raw-grid>.right-panel{grid-column:2}
.status-sidebar{display:flex;flex-direction:column;padding:8px;gap:8px;overflow:hidden}
.status-sidebar h2{margin:0;font-size:1rem;color:#d5ffe4}
.alert-banner{border-radius:8px;padding:9px 10px;background:#394047;color:#fff;font-weight:800;text-transform:uppercase;letter-spacing:.04em;text-align:center;border:1px solid #59636d}
.alert-banner.risk-danger{background:#7f1111;border-color:#ff4c4c;color:#fff}
.alert-banner.risk-caution{background:#735100;border-color:#ffc247;color:#fff4c2}
.alert-banner.risk-clear{background:#0f5e2a;border-color:#31d36b;color:#d6ffe4}
.alert-banner.risk-unknown{background:#303943;border-color:#65717e;color:#e8eef5}
.status-grid{display:grid;grid-template-columns:auto minmax(0,1fr);gap:5px 8px;font-size:.82rem;line-height:1.15;background:#10161a;border-radius:8px;border:1px solid #27333a;padding:8px;overflow:hidden}
.status-grid .k{color:#8fb0bf;text-transform:uppercase;font-size:.68rem;letter-spacing:.04em}
.status-grid .v{color:#e7f8ee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
.status-grid .danger{color:#ff6b6b;font-weight:800}.status-grid .caution{color:#ffd166;font-weight:800}.status-grid .clear{color:#65e987;font-weight:800}
.raw-json{min-height:0;flex:1;overflow:auto;background:#081014;border:1px solid #1f2b33;border-radius:8px;padding:8px;margin:0;color:#9fffc2;font-size:.66rem;line-height:1.15;white-space:pre-wrap;word-break:break-word}
@media (max-width:900px){
  body{overflow:auto}
  .debug-dashboard{height:auto;min-height:100vh;display:block;overflow:visible}
  .video-stack{display:block;overflow:visible}
  .stream-box{height:34vh;margin-bottom:8px}
  .combined-panel{height:42vh}
  .raw-grid{display:grid;grid-template-columns:1fr;grid-auto-rows:34vh;gap:8px;overflow:visible}
  .raw-grid>.stream-box{height:34vh;margin-bottom:0}
  .status-sidebar{height:auto;max-height:none;overflow:visible}
}
</style>
</head>
<body>
<div class="debug-dashboard">
  <main class="video-stack">
    <section class="stream-box combined-panel">
      <h3>Boxes + active camera UI / ACTIVE PRIMARY RISK COORDS</h3>
      <img src="/stream/combined" alt="Active primary camera with detection boxes and ARIA graphics">
    </section>
    <section class="raw-grid" aria-label="Physical raw camera streams">
      <div class="stream-box raw-panel left-panel">
        <h3>LEFT / BACKUP / raw stream</h3>
        <img src="/stream/left" alt="Left raw backup camera view">
      </div>
      <div class="stream-box raw-panel right-panel">
        <h3>RIGHT / MAIN / raw stream</h3>
        <img src="/stream/right" alt="Right raw main camera view">
      </div>
    </section>
  </main>
  <aside class="status-sidebar">
    <h2>ARIA Status</h2>
    <div id="alertBanner" class="alert-banner risk-unknown">connecting...</div>
    <div id="compactStatus" class="status-grid"></div>
    <pre id="status" class="raw-json">connecting...</pre>
  </aside>
</div>
<script>
const rawEl=document.getElementById('status');
const compactEl=document.getElementById('compactStatus');
const alertEl=document.getElementById('alertBanner');
function fmtQuality(q){
  if(!q || !q.status) return 'n/a';
  const score = Number.isFinite(q.score) ? ` ${q.score}` : '';
  return `${q.status}${score}`;
}
function riskClass(risk, alert){
  const text=`${risk||''} ${alert||''}`.toLowerCase();
  if(text.includes('danger')) return 'risk-danger';
  if(text.includes('caution')) return 'risk-caution';
  if(text.includes('clear')) return 'risk-clear';
  return 'risk-unknown';
}
function valueClass(value){
  const text=String(value||'').toLowerCase();
  if(text.includes('danger')) return 'danger';
  if(text.includes('caution')) return 'caution';
  if(text.includes('clear') || text.includes('good') || text === 'running') return 'clear';
  return '';
}
function row(k,v){
  const key=document.createElement('div');
  key.className='k';
  key.textContent=k;
  const value=document.createElement('div');
  const cls=valueClass(v);
  value.className=cls ? `v ${cls}` : 'v';
  value.title=String(v);
  value.textContent=String(v);
  return [key,value];
}
function renderStatus(j){
  const risk=j.risk || 'unknown';
  const alert=j.alert || 'none';
  const cls=riskClass(risk, alert);
  alertEl.className=`alert-banner ${cls}`;
  alertEl.textContent=`${risk.toUpperCase()} — ${alert}`;
  const fps=Number.isFinite(j.fps) ? j.fps.toFixed(1) : '0.0';
  const rows=[
    ['Camera', j.camera || 'n/a'],
    ['Active', j.active_primary_role || 'n/a'],
    ['Backup', j.backup_active ? 'ON' : 'off'],
    ['Main Q', fmtQuality(j.main_quality)],
    ['Backup Q', fmtQuality(j.backup_quality)],
    ['Detector', j.detector || 'n/a'],
    ['Det FPS', Number.isFinite(j.detector_fps) ? j.detector_fps.toFixed(1) : '0.0'],
    ['Loop ms', Number.isFinite(j.update_ms) ? j.update_ms.toFixed(1) : '0.0'],
    ['ToF C', j.tof_center_mm ?? 'n/a'],
    ['ToF L/R', `${j.tof_left_mm ?? 'n/a'} / ${j.tof_right_mm ?? 'n/a'}`],
    ['ToF sensors', `${j.tof_sensor_count ?? 0} ${Array.isArray(j.tof_roles) ? j.tof_roles.join(',') : ''}`],
    ['ToF zones', j.tof_valid_zones ?? 0],
    ['IMU', j.imu_status || 'n/a'],
    ['Heading', j.imu_heading_deg ?? 'n/a'],
    ['Roll/Pitch', `${j.imu_roll_deg ?? 'n/a'} / ${j.imu_pitch_deg ?? 'n/a'}`],
    ['FPS', fps],
    ['Frames', j.frame_count ?? 0],
  ].flatMap(([k,v]) => row(k,v));
  compactEl.replaceChildren(...rows);
}
async function poll(){
  try{
    const r=await fetch('/status',{cache:'no-store'});
    const j=await r.json();
    renderStatus(j);
    rawEl.textContent=JSON.stringify(j,null,2);
  }
  catch(e){
    alertEl.className='alert-banner risk-unknown';
    alertEl.textContent='POLL ERROR';
    rawEl.textContent='poll error: '+e;
  }
}
setInterval(poll,500);poll();
</script>
</body>
</html>
"""


def _make_handler(
    state: _SharedState,
    running: Callable[[], bool],
    stream_interval: float = 0.033,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._serve_html()
            elif path == "/stream":
                self._serve_stream("primary")
            elif path == "/stream/primary":
                self._serve_stream("primary")
            elif path == "/stream/secondary":
                self._serve_stream("secondary")
            elif path == "/stream/left":
                self._serve_stream("left")
            elif path == "/stream/right":
                self._serve_stream("right")
            elif path == "/stream/combined":
                self._serve_stream("combined")
            elif path == "/status":
                self._serve_status()
            else:
                self.send_error(404)

        def _serve_html(self) -> None:
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_stream(self, role: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            try:
                while running():
                    jpeg = state.get_jpeg(role)
                    if jpeg:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(stream_interval)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _serve_status(self) -> None:
            status = state.get_status()
            body = json.dumps(asdict(status), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class TofSerialReader:
    def __init__(self, port: str, baud: int = 115200) -> None:
        self.port = port
        self.baud = baud
        self.latest_sequence: int | None = None
        self.latest_status: int | None = None
        self.latest_distances: tuple[int | None, ...] = ()
        self.latest_frames: dict[str, TofFrame] = {}
        self.latest_imu: dict[str, Any] = {}
        self.latest_imu_time_s: float | None = None
        self._thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._lock = threading.Lock()
        self.error: str | None = None

    def start(self) -> bool:
        try:
            import serial  # type: ignore
        except Exception as exc:
            self.error = f"pyserial_unavailable: {exc}"
            return False
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
        except Exception as exc:
            self.error = f"serial_open_failed: {exc}"
            return False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        buffer = bytearray()
        while not self._shutdown.is_set():
            try:
                data = self._ser.read(512)
            except Exception as exc:
                self.error = f"serial_read_error: {exc}"
                time.sleep(0.05)
                continue
            if data:
                buffer.extend(data)
                while True:
                    start = self._find_frame_start(buffer)
                    if start < 0:
                        if b"\n" in buffer:
                            lines = buffer.split(b"\n")
                            buffer = bytearray(lines[-1])
                            for line in lines[:-1]:
                                self._parse_imu_line(bytes(line).strip())
                        else:
                            buffer = buffer[-BINARY_FRAME_SIZE:]
                        break
                    if start > 0:
                        prefix = bytes(buffer[:start])
                        if b"\n" in prefix:
                            for line in prefix.split(b"\n"):
                                self._parse_imu_line(line.strip())
                        buffer = buffer[start:]
                    frame_size = self._frame_size(buffer)
                    if frame_size is None or len(buffer) < frame_size:
                        break
                    candidate = bytes(buffer[:frame_size])
                    try:
                        packet = parse_any_binary_frame(candidate)
                        if packet.sensor_count == 0:
                            with self._lock:
                                self.latest_sequence = packet.sequence
                                self.latest_status = packet.status
                                self.latest_distances = ()
                                self.latest_frames = {}
                                self.error = "tof_sensor_error"
                            buffer = buffer[frame_size:]
                            continue
                        frame_set = packet.to_frame_set()
                        center_packet = packet.sensors.get("center") or next(iter(packet.sensors.values()))
                        with self._lock:
                            self.latest_sequence = packet.sequence
                            self.latest_status = packet.status
                            self.latest_distances = center_packet.distances_mm
                            self.latest_frames = frame_set.frames
                            self.error = None
                        buffer = buffer[frame_size:]
                    except ValueError:
                        buffer = buffer[1:]
            else:
                time.sleep(0.01)

    def _find_frame_start(self, buffer: bytearray) -> int:
        starts = [idx for idx in (buffer.find(MAGIC), buffer.find(MULTI_MAGIC)) if idx >= 0]
        return min(starts) if starts else -1

    def _frame_size(self, buffer: bytearray) -> int | None:
        if buffer.startswith(MAGIC):
            return BINARY_FRAME_SIZE
        if buffer.startswith(MULTI_MAGIC):
            if len(buffer) < 12:
                return None
            payload_len = int.from_bytes(buffer[10:12], "little")
            return 12 + payload_len + 2
        return None

    def _parse_imu_line(self, line: bytes) -> None:
        if not line:
            return
        try:
            text = line.decode("utf-8", errors="ignore").strip()
        except Exception:
            return
        if not text.startswith("IMU"):
            return
        payload: dict[str, Any] = {}
        try:
            if text.startswith("IMU{"):
                payload = json.loads(text[3:])
            elif text.startswith("IMU "):
                payload = json.loads(text[4:])
            elif text.startswith("IMU,"):
                parts = [part.strip() for part in text.split(",")]
                # IMU,heading,roll,pitch[,ax,ay,az,gx,gy,gz]
                values = [float(part) for part in parts[1:] if part != ""]
                if len(values) >= 3:
                    payload = {"heading_deg": values[0], "roll_deg": values[1], "pitch_deg": values[2]}
                if len(values) >= 6:
                    payload["accel"] = values[3:6]
                if len(values) >= 9:
                    payload["gyro"] = values[6:9]
        except Exception as exc:
            with self._lock:
                self.error = f"imu_parse_error: {exc}"
            return
        if payload:
            payload.setdefault("status", "ok")
            with self._lock:
                self.latest_imu = payload
                self.latest_imu_time_s = time.monotonic()

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            valid = [v for frame in self.latest_frames.values() for row in frame.distances_mm for v in row if v is not None and v > 0]
            distances = {role: frame.distance_for_region(Region.CENTER) for role, frame in self.latest_frames.items()}
            imu = dict(self.latest_imu)
            imu_age_s = None if self.latest_imu_time_s is None else time.monotonic() - self.latest_imu_time_s
            return {
                "sequence": self.latest_sequence,
                "status": self.latest_status,
                "valid_zones": len(valid),
                "center_mm": distances.get("center"),
                "left_mm": distances.get("left"),
                "right_mm": distances.get("right"),
                "sensor_count": len(self.latest_frames),
                "roles": sorted(self.latest_frames),
                "error": self.error,
                "imu": imu,
                "imu_age_s": imu_age_s,
            }

    def stop(self) -> None:
        self._shutdown.set()
        if hasattr(self, "_ser"):
            try:
                self._ser.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=1.0)


class WebDemo:
    def __init__(
        self,
        camera_config: CameraConfig | None = None,
        dual_camera_config: DualCameraConfig | None = None,
        tof_config: TofConfig | None = None,
        detector_config: DetectorConfig | None = None,
        ui_config: UiConfig | None = None,
        host: str = "0.0.0.0",
        port: int = 8080,
        stream_interval: float = 0.033,
        enable_web: bool = True,
    ) -> None:
        self.camera_config = camera_config or CameraConfig()
        self.dual_camera_config = dual_camera_config
        self.tof_config = tof_config or TofConfig()
        self.detector_config = detector_config or DetectorConfig()
        self.ui_config = ui_config or UiConfig()
        self.host = host
        self.port = port
        self.stream_interval = stream_interval
        self.enable_web = enable_web
        self.dual_mode = dual_camera_config is not None
        self._state = _SharedState()
        self._running = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        # single-camera
        self._camera: Camera | None = None
        # dual-camera
        self._multi_camera: MultiCamera | None = None
        self._primary_role: str = dual_camera_config.primary_role if dual_camera_config else "right"
        self._main_role: str = self._primary_role
        self._active_primary_role: str = self._main_role
        self._poor_main_since: float | None = None
        self._good_main_since: float | None = None
        self._quality_hold_until: dict[str, float] = {}
        self._held_qualities: dict[str, CameraQuality] = {}
        self._tof_reader: TofSerialReader | None = None
        self._detector = None
        self._detector_lock = threading.Lock()
        self._detector_shutdown = threading.Event()
        self._detector_thread: threading.Thread | None = None
        self._latest_detector_input: Any = None
        self._latest_detector_input_seq = 0
        self._processed_detector_input_seq = 0
        self._last_published_detector_token: tuple[str, int] | None = None
        self._detector_error: str | None = None
        self._renderer = OverlayRenderer()
        self._persistence = DetectionPersistence(ttl_s=self.ui_config.box_persistence_s)
        self._frame_count = 0
        self._last_counted_frame_token: tuple[str, int] | None = None
        self._fps_t0 = 0.0
        self._last_raw_encode_ts: float = 0.0
        self._last_detections: list[Any] = []
        self._last_detection_ts: float = 0.0
        self._detector_executor: ThreadPoolExecutor | None = None
        self._detector_future: Future[list[Any]] | None = None
        self._detector_started_at: float = 0.0
        self._detector_status: str = "not_loaded"
        self._detector_worker_local = threading.local()
        self._detector_count = 0
        self._detector_fps_t0 = 0.0
        self._last_detector_ms = 0.0

    def start(self) -> None:
        self._running.set()
        self._fps_t0 = time.monotonic()
        self._detector_fps_t0 = self._fps_t0

        # Start the HTTP server before hardware initialization so remote users
        # can load the status page even if camera/serial startup is slow.
        if self.enable_web:
            handler = _make_handler(self._state, self._running.is_set, self.stream_interval)
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
            self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._server_thread.start()

        # Camera(s)
        if self.dual_mode and self.dual_camera_config is not None:
            self._multi_camera = MultiCamera(self.dual_camera_config.cameras)
            self._multi_camera.open()
        else:
            self._camera = Camera(self.camera_config)
            self._camera.open()

        # ToF serial reader
        if self.tof_config.port:
            self._tof_reader = TofSerialReader(self.tof_config.port, self.tof_config.baud)
            self._tof_reader.start()

        # Detector
        if self.detector_config.model_path:
            try:
                from pathlib import Path

                model_path = self.detector_config.model_path
                if model_path is None or not Path(model_path).exists():
                    raise FileNotFoundError(f"HEF model not found: {model_path}")
                self._detector = self._detect_with_fresh_hailo
                self._detector_status = "running"
                self._detector_thread = threading.Thread(target=self._detector_loop, name="aria-detector", daemon=True)
                self._detector_thread.start()
            except Exception:
                self._detector = None
                self._detector_status = "not_loaded"

    def update_once(self) -> None:
        self._update()

    def _detector_loop(self) -> None:
        """Continuously run detection on the newest frame available.

        Polling a Future only once per UI frame capped detection at ~15 FPS when
        Hailo inference took just over one 30 FPS frame interval. This loop starts
        the next inference immediately after the previous one finishes, using the
        latest frame published by the UI thread.
        """

        while not self._detector_shutdown.is_set():
            with self._detector_lock:
                frame = self._latest_detector_input
                seq = self._latest_detector_input_seq
            if frame is None or seq == self._processed_detector_input_seq:
                time.sleep(0.001)
                continue
            self._processed_detector_input_seq = seq
            started = time.monotonic()
            self._detector_started_at = started
            self._detector_status = "busy"
            try:
                assert self._detector is not None
                detections = list(self._detector(frame))
                done = time.monotonic()
                with self._detector_lock:
                    self._last_detection_ts = done
                    self._detector_count += 1
                    self._last_detector_ms = max(0.0, (done - started) * 1000.0)
                    self._last_detections = detections
                    self._detector_error = None
                    self._detector_status = "running"
            except Exception as exc:
                with self._detector_lock:
                    self._detector_error = str(exc)
                    self._detector_status = f"error: {exc}"
                    self._last_detections = []
                time.sleep(0.05)

    def _publish_detector_frame(self, frame: Any) -> None:
        with self._detector_lock:
            self._latest_detector_input = frame
            self._latest_detector_input_seq += 1

    def _detector_snapshot(self) -> tuple[list[Any], str, str | None, float, float]:
        with self._detector_lock:
            detector_fps = self._detector_count / max(time.monotonic() - self._detector_fps_t0, 1e-9)
            return (
                list(self._last_detections),
                self._detector_status,
                self._detector_error,
                detector_fps,
                self._last_detector_ms,
            )

    def _detect_with_fresh_hailo(self, frame: Any) -> list[Any]:
        """Run Hailo inference on the dedicated detector worker thread.

        The worker owns a cached HailoDetector instance. This avoids reopening the
        HEF/VDevice for every frame, which was the largest FPS hit, while still
        keeping Hailo open/infer calls on one stable thread.
        """
        from aria.detector import HailoDetector

        model_path = self.detector_config.model_path
        if model_path is None:
            raise FileNotFoundError("HEF model path is not configured")
        detector = getattr(self._detector_worker_local, "detector", None)
        detector_key = getattr(self._detector_worker_local, "detector_key", None)
        key = (
            str(model_path),
            self.detector_config.confidence_threshold,
            self.detector_config.input_size,
            self.detector_config.quantized_input,
        )
        if detector is None or detector_key != key:
            if detector is not None:
                try:
                    detector.close()
                except Exception:
                    pass
            detector = HailoDetector(
                model_path=model_path,
                confidence_threshold=self.detector_config.confidence_threshold,
                input_size=self.detector_config.input_size,
                quantized_input=self.detector_config.quantized_input,
            )
            detector.open()
            self._detector_worker_local.detector = detector
            self._detector_worker_local.detector_key = key
        return detector.detect(frame)

    def _tof_frame(self) -> TofFrame | TofFrameSet | None:
        if self._tof_reader is None:
            return None
        if self._tof_reader.latest_frames:
            return TofFrameSet(dict(self._tof_reader.latest_frames))
        distances = self._tof_reader.latest_distances
        if len(distances) != 64:
            return None
        rows = tuple(tuple(distances[row * 8 : (row + 1) * 8]) for row in range(8))
        return TofFrameSet({"center": TofFrame(rows, sequence=self._tof_reader.latest_sequence, status=self._tof_reader.latest_status or 0)})

    def _backup_role(self) -> str | None:
        if not self.dual_camera_config:
            return None
        for role in self.dual_camera_config.cameras:
            if role != self._main_role:
                return role
        return None

    def _clear_detection_cache(self) -> None:
        self._last_detections = []
        self._last_detection_ts = 0.0
        self._persistence.clear()

    def _quality_with_failure_hold(self, role: str, raw_quality: CameraQuality, now: float) -> CameraQuality:
        """Keep camera failure/poor reasons visible briefly instead of flapping to good.

        Threaded UVC capture can fail for one/few reads and then immediately return
        another frame. Without a hold, the UI shows the failure reason for only one
        poll and then reports ``good``, making real camera dropouts hard to see and
        allowing active-camera recovery to happen too eagerly.
        """

        hold_s = 0.0
        if self.dual_camera_config and role in self.dual_camera_config.cameras:
            hold_s = max(0.0, self.dual_camera_config.cameras[role].failure_hold_s)
        else:
            hold_s = max(0.0, self.camera_config.failure_hold_s)
        if hold_s <= 0:
            return raw_quality

        if raw_quality.status != "good":
            self._held_qualities[role] = raw_quality
            self._quality_hold_until[role] = now + hold_s
            return raw_quality

        until = self._quality_hold_until.get(role)
        held = self._held_qualities.get(role)
        if until is not None and held is not None:
            if now < until:
                return CameraQuality(
                    status=held.status,
                    mean=held.mean,
                    std=held.std,
                    under_ratio=held.under_ratio,
                    over_ratio=held.over_ratio,
                    lap_var=held.lap_var,
                    score=held.score,
                    reason=f"held:{held.reason}",
                )
            self._quality_hold_until.pop(role, None)
            self._held_qualities.pop(role, None)
        return raw_quality

    def _update_active_primary(
        self,
        qualities: dict[str, CameraQuality],
        *,
        now: float,
    ) -> bool:
        backup_role = self._backup_role()
        main_quality = qualities.get(self._main_role)
        backup_quality = qualities.get(backup_role) if backup_role else None
        main_good = bool(main_quality and main_quality.usable)
        backup_good = bool(backup_quality and backup_quality.usable)

        previous_role = self._active_primary_role
        main_failed = bool(main_quality and main_quality.status == "failed")

        if main_good:
            self._poor_main_since = None
            if self._active_primary_role != self._main_role:
                if self._good_main_since is None:
                    self._good_main_since = now
                if now - self._good_main_since >= self.ui_config.main_recover_after_s:
                    self._active_primary_role = self._main_role
                    self._good_main_since = None
            else:
                self._good_main_since = now
        else:
            self._good_main_since = None
            if self._poor_main_since is None:
                self._poor_main_since = now
            should_switch = main_failed or (now - self._poor_main_since >= self.ui_config.backup_switch_after_s)
            if backup_role and backup_good and should_switch:
                self._active_primary_role = backup_role

        changed = self._active_primary_role != previous_role
        if changed:
            self._clear_detection_cache()
        return changed

    def _update(self) -> None:
        update_started = time.perf_counter()
        status = DemoStatus()
        status.dual_mode = self.dual_mode
        status.primary_role = self._primary_role
        status.active_primary_role = self._active_primary_role
        status.main_role = self._main_role
        status.backup_role = self._backup_role()
        status.backup_active = self._active_primary_role != self._main_role
        status.tof_port = self.tof_config.port
        status.timestamp = time.time()

        # Read ToF
        if self._tof_reader is not None:
            tof_summary = self._tof_reader.get_summary()
            status.tof_sequence = tof_summary.get("sequence")
            status.tof_status = tof_summary.get("status")
            status.tof_valid_zones = tof_summary.get("valid_zones", 0)
            status.tof_center_mm = tof_summary.get("center_mm")
            status.tof_left_mm = tof_summary.get("left_mm")
            status.tof_right_mm = tof_summary.get("right_mm")
            status.tof_sensor_count = tof_summary.get("sensor_count", 0)
            status.tof_roles = list(tof_summary.get("roles", []))
            imu = tof_summary.get("imu") or {}
            imu_age_s = tof_summary.get("imu_age_s")
            if imu:
                status.imu_status = "stale" if imu_age_s is not None and imu_age_s > 2.0 else str(imu.get("status", "ok"))
                status.imu_heading_deg = imu.get("heading_deg") or imu.get("heading")
                status.imu_roll_deg = imu.get("roll_deg") or imu.get("roll")
                status.imu_pitch_deg = imu.get("pitch_deg") or imu.get("pitch")
                status.imu_accel = imu.get("accel")
                status.imu_gyro = imu.get("gyro")
                status.imu_calibration = imu.get("calibration") or imu.get("calib")
            elif self._tof_reader is not None:
                status.imu_status = "no_imu_data"
            if tof_summary.get("error"):
                status.alert = f"tof_error: {tof_summary['error']}"
            else:
                region_distances = {
                    Region.LEFT: status.tof_left_mm,
                    Region.CENTER: status.tof_center_mm,
                    Region.RIGHT: status.tof_right_mm,
                }
                if status.tof_sensor_count <= 1 and status.tof_center_mm is not None:
                    region_distances = {Region.CENTER: status.tof_center_mm}
                risks = [
                    str(score_risk(region=region, distance_mm=distance).value)
                    for region, distance in region_distances.items()
                    if distance is not None
                ]
                if risks:
                    if any(risk == "danger" for risk in risks):
                        status.risk = "danger"
                        status.alert = "tof_danger"
                    elif any(risk == "caution" for risk in risks):
                        status.risk = "caution"
                        status.alert = "tof_caution"
                    elif all(risk == "clear" for risk in risks):
                        status.risk = "clear"

        # Camera read (dual-combined or single)
        combined_frame = None
        offsets: dict[str, Any] = {}
        frame: Any = None
        dual_frames: dict[str, CameraFrame | None] = {}
        single_cam_frame: CameraFrame | None = None

        if self.dual_mode and self._multi_camera is not None:
            frames = self._multi_camera.read_frames()
            dual_frames = frames
            now_mono = time.monotonic()
            raw_qualities = {
                role: assess_frame_quality(cam_frame.image if cam_frame is not None else None)
                for role, cam_frame in frames.items()
            }
            qualities = {
                role: self._quality_with_failure_hold(role, quality, now_mono)
                for role, quality in raw_qualities.items()
            }
            self._update_active_primary(qualities, now=now_mono)
            status.active_primary_role = self._active_primary_role
            status.backup_active = self._active_primary_role != self._main_role
            if self._main_role in qualities:
                status.main_quality = qualities[self._main_role].as_dict()
            backup_role = self._backup_role()
            if backup_role and backup_role in qualities:
                status.backup_quality = qualities[backup_role].as_dict()

            active_frame = frames.get(self._active_primary_role)
            if active_frame is not None and active_frame.image is not None:
                frame = active_frame.image.copy() if hasattr(active_frame.image, "copy") else active_frame.image
                combined_frame = frame
                status.camera = f"active_{self._active_primary_role} ({len([f for f in frames.values() if f is not None])} cameras)"
                h, w = frame.shape[:2]
                offsets = {
                    self._active_primary_role: {
                        "x_offset": 0,
                        "scale": 1.0,
                        "original_shape": (h, w),
                    }
                }
                status.cameras = {
                    role: {
                        "status": self._multi_camera.cameras[role].status,
                        "source": self.dual_camera_config.cameras[role].source if self.dual_camera_config else None,
                        "active": role == self._active_primary_role,
                    }
                    for role in self._multi_camera.cameras
                }
            else:
                status.camera = "active_unavailable"
            if frame is not None:
                token = (self._active_primary_role, active_frame.index) if active_frame is not None else None
                if token is not None and token != self._last_counted_frame_token:
                    self._frame_count += 1
                    self._last_counted_frame_token = token
        elif self._camera is not None:
            single_cam_frame = self._camera.read_frame()
            if single_cam_frame is not None:
                frame = single_cam_frame.image
                token = ("primary", single_cam_frame.index)
                if token != self._last_counted_frame_token:
                    self._frame_count += 1
                    self._last_counted_frame_token = token
            status.camera = getattr(self._camera, "status", "not_initialized") if self._camera else "no_camera"

        # Render placeholder if no camera frame but cv2/numpy available
        if frame is None and cv2 is not None and np is not None:
            h = self.camera_config.height
            w = self.camera_config.width
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            self._draw_center_text(frame, "Camera unavailable", (w // 2, h // 2))

        # Detect, fuse with the latest 8x8 ToF frame, then apply short UI persistence.
        detections: list[Any] = []
        fused_detections: list[Any] = []
        display_detection_source: list[Any] = []
        display_detections: list[Any] = []
        now = time.monotonic()
        status.detector = self._detector_status if self._detector is not None else "not_loaded"
        if self._detector is not None:
            if self._detector_thread is None and self._detector_future is not None and self._detector_future.done():
                try:
                    detector_done_at = time.monotonic()
                    detections = self._detector_future.result()
                    self._last_detection_ts = detector_done_at
                    self._detector_count += 1
                    self._last_detector_ms = max(0.0, (detector_done_at - self._detector_started_at) * 1000.0)
                    self._last_detections = list(detections)
                    self._detector_status = "running"
                    if not detections:
                        self._persistence.clear()
                except Exception as exc:
                    self._detector_status = f"error: {exc}"
                    status.alert = f"detector: {exc}"
                    self._last_detections = []
                    self._persistence.clear()
                finally:
                    self._detector_future = None

            # Choose detection frame: primary camera only (not combined display)
            det_frame: Any = None
            det_frame_token: tuple[str, int] | None = None
            if self.dual_mode and self._multi_camera is not None:
                primary = dual_frames.get(self._active_primary_role)
                if primary is not None and primary.image is not None:
                    det_frame = primary.image
                    det_frame_token = (self._active_primary_role, primary.index)
            elif single_cam_frame is not None and single_cam_frame.image is not None:
                det_frame = single_cam_frame.image
                det_frame_token = ("primary", single_cam_frame.index)

            if det_frame is not None:
                if self._detector_thread is not None:
                    if det_frame_token is None or det_frame_token != self._last_published_detector_token:
                        self._publish_detector_frame(det_frame)
                        self._last_published_detector_token = det_frame_token
                    detections, detector_status, detector_error, detector_fps, detector_ms = self._detector_snapshot()
                    status.detector = detector_status
                    status.detector_fps = detector_fps
                    status.detector_ms = detector_ms
                    if detector_error:
                        status.alert = f"detector: {detector_error}"
                    if not detections:
                        self._persistence.clear()
                else:
                    if self._detector_future is None and (now - self._last_detection_ts) >= self.ui_config.detection_interval_s:
                        sync_detect: Callable[[Any], list[Any]] | None = None
                        if self._detector_executor is not None:
                            detect_input = det_frame.copy() if hasattr(det_frame, "copy") else det_frame
                            self._detector_future = self._detector_executor.submit(self._detector, detect_input)
                            self._detector_started_at = now
                            self._detector_status = "busy"
                        else:
                            candidate = getattr(self._detector, "detect", None)
                            if callable(candidate):
                                sync_detect = cast(Callable[[Any], list[Any]], candidate)
                        if sync_detect is not None:
                            try:
                                detections = list(sync_detect(det_frame))
                                self._last_detection_ts = now
                                self._last_detections = list(detections)
                                if not detections:
                                    self._persistence.clear()
                            except Exception as exc:
                                self._detector_status = f"error: {exc}"
                                status.alert = f"detector: {exc}"
                                self._last_detections = []
                                self._persistence.clear()
                    elif self._detector_future is not None:
                        self._detector_status = f"busy {now - self._detector_started_at:.1f}s"
                    detections = self._last_detections
                    status.detector = self._detector_status

                # Fuse with ToF
                if detections:
                    tof_frame = self._tof_frame()
                    det_shape = det_frame.shape if det_frame is not None else (frame.shape if frame is not None else (480, 640))
                    fused_detections = [fuse_detection(det, det_shape, tof_frame) for det in detections]
                    risks = [str(getattr(item.risk, "value", item.risk)) for item in fused_detections]
                    if any("danger" in risk for risk in risks):
                        status.risk = "danger"
                        status.alert = "danger"
                    elif any("caution" in risk for risk in risks):
                        status.risk = "caution"
                        if status.alert in {"none", "tof_caution"}:
                            status.alert = "caution"
                    elif fused_detections and status.risk not in {"danger", "caution"}:
                        status.risk = "clear" if all("clear" in risk for risk in risks) else "unknown"

                    # Risk/fusion and display are now both in the active camera
                    # coordinate system: /stream/combined shows only the active
                    # primary image with boxes/text over it, while left/right raw
                    # panels remain separate physical-camera streams.
                    display_detection_source = fused_detections
                else:
                    display_detection_source = detections

        status.detection_count = len(detections)
        status.detector_fps = self._detector_count / max(time.monotonic() - self._detector_fps_t0, 1e-9)
        status.detector_ms = self._last_detector_ms
        jpegs: dict[str, bytes] = {}
        now_for_raw = time.monotonic()
        raw_interval = 1.0 / max(self.ui_config.raw_stream_fps, 0.1)
        encode_raw_streams = self.dual_mode and (now_for_raw - self._last_raw_encode_ts) >= raw_interval
        if encode_raw_streams:
            self._last_raw_encode_ts = now_for_raw
            # Refresh or explicitly clear raw streams at a lower rate. Encoding
            # left + right + active JPEGs every tick was the main 15-17 FPS cap.
            jpegs.update({"left": b"", "right": b"", "primary": b"", "secondary": b""})
        if frame is not None:
            display_detections = self._persistence.update(
                display_detection_source,
                image_width=frame.shape[1] if hasattr(frame, "shape") else None,
            )
        status.frame_count = self._frame_count
        if frame is not None and cv2 is not None:
            status.fps = self._frame_count / max(time.monotonic() - self._fps_t0, 1e-9)
            if encode_raw_streams:
                for role in ("left", "right"):
                    raw_frame = dual_frames.get(role)
                    if raw_frame is None or raw_frame.image is None:
                        continue
                    raw_image = self._resize_for_stream(raw_frame.image)
                    raw_jpeg = _encode_jpeg(raw_image, quality=self.ui_config.jpeg_quality)
                    if raw_jpeg:
                        jpegs[role] = raw_jpeg
                        if role == "left":
                            jpegs["secondary"] = raw_jpeg
                        elif role == "right":
                            jpegs["primary"] = raw_jpeg
            image = self._renderer.render(frame, status, detections=display_detections)
            image = self._resize_for_stream(image)
            jpeg = _encode_jpeg(image, quality=self.ui_config.jpeg_quality)
            if jpeg:
                if self.dual_mode:
                    jpegs["combined"] = jpeg
                else:
                    jpegs["primary"] = jpeg
            status.update_ms = (time.perf_counter() - update_started) * 1000.0
            self._state.update(jpeg=jpegs, status=status)
        else:
            status.update_ms = (time.perf_counter() - update_started) * 1000.0
            self._state.update(jpeg=jpegs if self.dual_mode else None, status=status)

    def _resize_for_stream(self, image: Any) -> Any:
        max_width = self.ui_config.stream_max_width
        if cv2 is None or image is None or max_width <= 0:
            return image
        h, w = image.shape[:2]
        if w <= max_width:
            return image
        scale = max_width / float(w)
        return cv2.resize(image, (max_width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)

    def _draw_center_text(self, image: Any, text: str, center: tuple[int, int]) -> None:
        if cv2 is None:
            return
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
        x = center[0] - tw // 2
        y = center[1] + th // 2
        cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

    def run(self) -> None:
        if self.enable_web:
            print(f"ARIA web demo starting at http://{self.host}:{self.port}/")
        else:
            print("ARIA demo pipeline starting without web UI")
        try:
            next_tick = time.monotonic()
            while self._running.is_set():
                self._update()
                next_tick += self.stream_interval
                sleep_s = next_tick - time.monotonic()
                if sleep_s > 0:
                    time.sleep(sleep_s)
                else:
                    # Do not add a fixed sleep after an overrun; recover toward
                    # the requested web FPS instead of halving the frame rate.
                    next_tick = time.monotonic()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._running.clear()
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._detector is not None:
            try:
                close = getattr(self._detector, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
        if self._detector_executor is not None:
            self._detector_executor.shutdown(wait=False, cancel_futures=True)
            self._detector_executor = None
        self._detector_shutdown.set()
        if self._detector_thread is not None:
            self._detector_thread.join(timeout=1.0)
            self._detector_thread = None
        if self._tof_reader:
            self._tof_reader.stop()
        if self._multi_camera is not None:
            self._multi_camera.release()
        if self._camera:
            self._camera.release()
