"""Lightweight browser UI for ARIA v0.

Uses Python stdlib ``http.server`` to serve an HTML dashboard with an MJPEG
stream and a JSON status endpoint. OpenCV overlays are drawn when available.
Missing cv2, camera, or serial produce clear status messages instead of crashes.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

from aria.camera import Camera, CameraConfig
from aria.config import DetectorConfig, TofConfig, UiConfig
from aria.distance import BINARY_FRAME_SIZE, MAGIC, parse_binary_frame
from aria.fusion import Region, TofFrame, fuse_detection, score_risk
from aria.tracker import DetectionPersistence


@dataclass
class DemoStatus:
    camera: str = "not_initialized"
    fps: float = 0.0
    frame_count: int = 0
    detection_count: int = 0
    detector: str = "not_initialized"
    tof_port: str | None = None
    tof_sequence: int | None = None
    tof_status: int | None = None
    tof_valid_zones: int = 0
    tof_center_mm: int | None = None
    alert: str = "none"
    risk: str = "unknown"
    timestamp: float = field(default_factory=time.time)


class _SharedState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: bytes = b""
        self._status = DemoStatus()

    def update(self, jpeg: bytes | None = None, status: DemoStatus | None = None) -> None:
        with self._lock:
            if jpeg is not None:
                self._jpeg = jpeg
            if status is not None:
                self._status = status

    def get(self) -> tuple[bytes, DemoStatus]:
        with self._lock:
            return self._jpeg[:], self._status


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


def _encode_jpeg(image: Any, quality: int = 85) -> bytes | None:
    if cv2 is None or image is None:
        return None
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else None


HTML_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>ARIA v0 Demo</title>
<style>
body{font-family:sans-serif;background:#111;color:#0f0;margin:0;padding:8px}
.wrap{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start}
img{border:1px solid #333;max-width:100%;height:auto}
.panel{background:#222;padding:10px;border-radius:4px;min-width:200px}
h2{margin:0 0 8px;font-size:1.1rem}
pre{margin:0;font-size:0.9rem}
</style>
</head>
<body>
<div class="wrap">
<img src="/stream" alt="ARIA camera stream">
<div class="panel">
<h2>Status</h2>
<pre id="status">connecting...</pre>
</div>
</div>
<script>
const el=document.getElementById('status');
async function poll(){
  try{const r=await fetch('/status');const j=await r.json();el.textContent=JSON.stringify(j,null,2);}
  catch(e){el.textContent='poll error: '+e;}
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
            if self.path == "/":
                self._serve_html()
            elif self.path == "/stream":
                self._serve_stream()
            elif self.path == "/status":
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

        def _serve_stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            try:
                while running():
                    jpeg, _ = state.get()
                    if jpeg:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(stream_interval)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _serve_status(self) -> None:
            _, status = state.get()
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
                data = self._ser.read(256)
            except Exception as exc:
                self.error = f"serial_read_error: {exc}"
                time.sleep(0.05)
                continue
            if data:
                buffer.extend(data)
                while True:
                    start = buffer.find(MAGIC)
                    if start < 0:
                        buffer = buffer[-BINARY_FRAME_SIZE:]
                        break
                    if start + BINARY_FRAME_SIZE > len(buffer):
                        if start > 0:
                            buffer = buffer[start:]
                        break
                    candidate = bytes(buffer[start : start + BINARY_FRAME_SIZE])
                    try:
                        packet = parse_binary_frame(candidate)
                        with self._lock:
                            self.latest_sequence = packet.sequence
                            self.latest_status = packet.status
                            self.latest_distances = packet.distances_mm
                            self.error = None
                        buffer = buffer[start + BINARY_FRAME_SIZE :]
                    except ValueError:
                        buffer = buffer[start + 1 :]
            else:
                time.sleep(0.01)

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            valid = [v for v in self.latest_distances if v is not None and v > 0]
            center_values = []
            if len(self.latest_distances) == 64:
                for row in range(8):
                    for col in range(2, 6):
                        v = self.latest_distances[row * 8 + col]
                        if v is not None and v > 0:
                            center_values.append(v)
            return {
                "sequence": self.latest_sequence,
                "status": self.latest_status,
                "valid_zones": len(valid),
                "center_mm": int(sum(center_values) / len(center_values)) if center_values else None,
                "error": self.error,
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
        tof_config: TofConfig | None = None,
        detector_config: DetectorConfig | None = None,
        ui_config: UiConfig | None = None,
        host: str = "0.0.0.0",
        port: int = 8080,
        stream_interval: float = 0.033,
        enable_web: bool = True,
    ) -> None:
        self.camera_config = camera_config or CameraConfig()
        self.tof_config = tof_config or TofConfig()
        self.detector_config = detector_config or DetectorConfig()
        self.ui_config = ui_config or UiConfig()
        self.host = host
        self.port = port
        self.stream_interval = stream_interval
        self.enable_web = enable_web
        self._state = _SharedState()
        self._running = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._camera: Camera | None = None
        self._tof_reader: TofSerialReader | None = None
        self._detector = None
        self._renderer = OverlayRenderer()
        self._persistence = DetectionPersistence(ttl_s=self.ui_config.box_persistence_s)
        self._frame_count = 0
        self._fps_t0 = 0.0

    def start(self) -> None:
        self._running.set()
        self._fps_t0 = time.monotonic()

        # Start the HTTP server before hardware initialization so remote users
        # can load the status page even if camera/serial startup is slow.
        if self.enable_web:
            handler = _make_handler(self._state, self._running.is_set, self.stream_interval)
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
            self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._server_thread.start()

        # Camera
        self._camera = Camera(self.camera_config)
        self._camera.open()

        # ToF serial reader
        if self.tof_config.port:
            self._tof_reader = TofSerialReader(self.tof_config.port, self.tof_config.baud)
            self._tof_reader.start()

        # Detector
        if self.detector_config.model_path:
            try:
                from aria.detector import HailoDetector
                self._detector = HailoDetector(
                    model_path=self.detector_config.model_path,
                    confidence_threshold=self.detector_config.confidence_threshold,
                    input_size=self.detector_config.input_size,
                    quantized_input=self.detector_config.quantized_input,
                )
                self._detector.open()
            except Exception:
                self._detector = None

    def update_once(self) -> None:
        self._update()

    def _tof_frame(self) -> TofFrame | None:
        if self._tof_reader is None:
            return None
        distances = self._tof_reader.latest_distances
        if len(distances) != 64:
            return None
        rows = tuple(tuple(distances[row * 8 : (row + 1) * 8]) for row in range(8))
        return TofFrame(rows, sequence=self._tof_reader.latest_sequence, status=self._tof_reader.latest_status or 0)

    def _update(self) -> None:
        status = DemoStatus()
        status.camera = getattr(self._camera, "status", "not_initialized") if self._camera else "no_camera"
        status.tof_port = self.tof_config.port
        status.timestamp = time.time()

        # Read ToF
        if self._tof_reader is not None:
            tof_summary = self._tof_reader.get_summary()
            status.tof_sequence = tof_summary.get("sequence")
            status.tof_status = tof_summary.get("status")
            status.tof_valid_zones = tof_summary.get("valid_zones", 0)
            status.tof_center_mm = tof_summary.get("center_mm")
            if tof_summary.get("error"):
                status.alert = f"tof_error: {tof_summary['error']}"
            elif status.tof_center_mm is not None:
                tof_risk = str(score_risk(region=Region.CENTER, distance_mm=status.tof_center_mm).value)
                status.risk = tof_risk
                if tof_risk in {"danger", "caution"}:
                    status.alert = f"tof_{tof_risk}"

        # Read camera
        frame = None
        if self._camera is not None:
            cam_frame = self._camera.read_frame()
            if cam_frame is not None:
                frame = cam_frame.image
                self._frame_count += 1

        # Render placeholder if no camera frame but cv2/numpy available
        if frame is None and cv2 is not None and np is not None:
            h = self.camera_config.height
            w = self.camera_config.width
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            self._draw_center_text(frame, "Camera unavailable", (w // 2, h // 2))

        # Detect, fuse with the latest 8x8 ToF frame, then apply short UI persistence.
        detections: list[Any] = []
        fused_detections: list[Any] = []
        display_detections: list[Any] = []
        status.detector = "running" if self._detector is not None else "not_loaded"
        if self._detector is not None and frame is not None:
            try:
                detections = self._detector.detect(frame)
                tof_frame = self._tof_frame()
                fused_detections = [fuse_detection(det, frame.shape, tof_frame) for det in detections]
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
            except Exception as exc:
                status.detector = f"error: {exc}"
                status.alert = f"detector: {exc}"

        status.detection_count = len(detections)
        if frame is not None:
            display_detections = self._persistence.update(
                fused_detections if fused_detections else detections,
                image_width=frame.shape[1] if hasattr(frame, "shape") else None,
            )
        status.frame_count = self._frame_count
        if frame is not None and cv2 is not None:
            status.fps = self._frame_count / max(time.monotonic() - self._fps_t0, 1e-9)
            image = self._renderer.render(frame, status, detections=display_detections)
            jpeg = _encode_jpeg(image)
            if jpeg:
                self._state.update(jpeg=jpeg, status=status)
        else:
            self._state.update(status=status)

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
            while self._running.is_set():
                self._update()
                time.sleep(self.stream_interval)
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
                self._detector.close()
            except Exception:
                pass
        if self._tof_reader:
            self._tof_reader.stop()
        if self._camera:
            self._camera.release()
