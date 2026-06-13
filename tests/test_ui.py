import http.client
import threading
import time

import pytest

from aria.ui import (
    DemoStatus,
    HTML_PAGE,
    OverlayRenderer,
    TofSerialReader,
    WebDemo,
    _SharedState,
    _encode_jpeg,
    _make_handler,
)
from aria.config import DetectorConfig
from aria.quality import CameraQuality


def test_demo_status_defaults():
    s = DemoStatus()
    assert s.camera == "not_initialized"
    assert s.fps == 0.0
    assert s.alert == "none"
    assert s.tof_valid_zones == 0


def test_shared_state_round_trip():
    st = _SharedState()
    st.update(jpeg=b"hello", status=DemoStatus(camera="ok"))
    jpeg, status = st.get()
    assert jpeg == b"hello"
    assert status.camera == "ok"


def test_shared_state_thread_safety():
    st = _SharedState()
    errors = []

    def writer():
        try:
            for i in range(100):
                st.update(jpeg=f"frame{i}".encode(), status=DemoStatus(frame_count=i))
                time.sleep(0.0001)
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            for _ in range(100):
                st.get()
                time.sleep(0.0001)
        except Exception as exc:
            errors.append(exc)

    w = threading.Thread(target=writer)
    r = threading.Thread(target=reader)
    w.start()
    r.start()
    w.join()
    r.join()
    assert not errors


def test_overlay_renderer_returns_none_when_cv2_missing(monkeypatch):
    monkeypatch.setattr("aria.ui.cv2", None)
    r = OverlayRenderer()
    assert r.render("not_an_image", DemoStatus()) == "not_an_image"


def test_overlay_renderer_draws_when_cv2_present(monkeypatch):
    calls = []

    class FakeCv2:
        FONT_HERSHEY_SIMPLEX = 0
        IMWRITE_JPEG_QUALITY = 1

        @staticmethod
        def putText(img, text, org, font, scale, color, thickness, lineType=None):
            calls.append(("putText", text, org, color))

        @staticmethod
        def line(img, pt1, pt2, color, thickness):
            calls.append(("line", pt1, pt2, color))

    monkeypatch.setattr("aria.ui.cv2", FakeCv2())
    r = OverlayRenderer()

    class FakeImage:
        shape = (480, 640, 3)

    image = FakeImage()
    status = DemoStatus(camera="open", fps=30.0, alert="none")
    result = r.render(image, status)
    assert result is image
    texts = [c[1] for c in calls if c[0] == "putText"]
    assert any("CAM:" in t for t in texts)
    assert any("ALERT:" in t for t in texts)
    assert any("ToF:" in t for t in texts)


def test_encode_jpeg_returns_none_when_cv2_missing(monkeypatch):
    monkeypatch.setattr("aria.ui.cv2", None)
    assert _encode_jpeg(None) is None


def test_make_handler_returns_subclass():
    state = _SharedState()
    handler_cls = _make_handler(state, lambda: True)
    from http.server import BaseHTTPRequestHandler

    assert issubclass(handler_cls, BaseHTTPRequestHandler)


def test_webdemo_init():
    demo = WebDemo(host="127.0.0.1", port=0)
    assert demo.host == "127.0.0.1"
    assert demo.port == 0
    assert demo._camera is None


def test_webdemo_start_stop_without_hardware(monkeypatch):
    monkeypatch.setattr("aria.ui.cv2", None)
    monkeypatch.setattr("aria.ui.np", None)
    monkeypatch.setattr("aria.camera.Camera.open", lambda self: False)
    demo = WebDemo(host="127.0.0.1", port=0)
    demo.start()
    time.sleep(0.1)
    demo.stop()
    assert not demo._running.is_set()


def test_webdemo_reports_detector_load_error(monkeypatch):
    monkeypatch.setattr("aria.camera.Camera.open", lambda self: False)
    demo = WebDemo(
        enable_web=False,
        detector_config=DetectorConfig(model_path="/tmp/aria_missing_model.hef"),
    )
    demo.start()
    demo.update_once()
    status = demo._state.get_status()
    demo.stop()

    assert "HEF model not found" in status.detector
    assert status.detector_error is not None
    assert status.detector_model_path == "/tmp/aria_missing_model.hef"


def test_webdemo_serves_status_and_html(monkeypatch):
    monkeypatch.setattr("aria.camera.Camera.open", lambda self: False)
    demo = WebDemo(host="127.0.0.1", port=0)
    demo.start()
    time.sleep(0.1)
    port = demo._server.server_address[1]

    conn = http.client.HTTPConnection("127.0.0.1", port)

    conn.request("GET", "/")
    resp = conn.getresponse()
    assert resp.status == 200
    body = resp.read()
    assert b"<title>ARIA v0 Demo</title>" in body

    conn.request("GET", "/status")
    resp = conn.getresponse()
    assert resp.status == 200
    data = resp.read()
    assert b'"camera"' in data

    conn.close()
    demo.stop()


def test_single_camera_update_reads_camera_once_with_detector(monkeypatch):
    np = pytest.importorskip("numpy")

    class FakeDetector:
        def detect(self, frame):
            return []

    demo = WebDemo(enable_web=False)
    demo._detector = FakeDetector()
    frame = type("Frame", (), {"image": np.zeros((40, 60, 3), dtype=np.uint8), "index": 1})()
    camera = type("Camera", (), {"status": "open", "reads": 0})()
    def read_frame():
        camera.reads += 1
        return frame
    camera.read_frame = read_frame
    demo._camera = camera
    monkeypatch.setattr(demo._renderer, "render", lambda image, status, detections=None: image)

    demo._update()

    assert camera.reads == 1


def test_html_page_uses_720p_debug_dashboard_layout():
    assert 'class="debug-dashboard"' in HTML_PAGE
    assert 'combined-panel' in HTML_PAGE
    assert 'raw-grid' in HTML_PAGE
    assert 'status-sidebar' in HTML_PAGE
    assert 'id="alertBanner"' in HTML_PAGE
    assert 'id="compactStatus"' in HTML_PAGE
    assert 'height:100vh' in HTML_PAGE
    assert 'overflow:hidden' in HTML_PAGE
    assert 'RIGHT / MAIN / raw stream' in HTML_PAGE
    assert 'LEFT / BACKUP / raw stream' in HTML_PAGE
    assert HTML_PAGE.index('LEFT / BACKUP / raw stream') < HTML_PAGE.index('RIGHT / MAIN / raw stream')
    assert '.raw-grid>.left-panel{grid-column:1}' in HTML_PAGE
    assert '.raw-grid>.right-panel{grid-column:2}' in HTML_PAGE


def test_html_page_compact_status_script_surfaces_key_debug_fields():
    for field in [
        'active_primary_role',
        'backup_active',
        'main_quality',
        'backup_quality',
        'tof_center_mm',
        'tof_valid_zones',
        'detector',
        'detector_error',
        'detector_model_path',
        'fps',
        'risk',
        'alert',
    ]:
        assert field in HTML_PAGE
    assert 'risk-danger' in HTML_PAGE
    assert 'risk-caution' in HTML_PAGE
    assert 'risk-clear' in HTML_PAGE


def test_compact_status_uses_text_nodes_instead_of_innerhtml():
    assert 'function row(k,v)' in HTML_PAGE
    assert 'document.createElement' in HTML_PAGE
    assert '.textContent=' in HTML_PAGE
    assert 'compactEl.replaceChildren' in HTML_PAGE
    assert 'compactEl.innerHTML' not in HTML_PAGE


def test_failure_quality_is_held_briefly_before_returning_to_good():
    demo = WebDemo(enable_web=False)
    failed = CameraQuality(status="failed", reason="read_failed")
    good = CameraQuality(status="good", reason="usable")

    assert demo._quality_with_failure_hold("right", failed, 10.0).status == "failed"
    held = demo._quality_with_failure_hold("right", good, 10.5)
    assert held.status == "failed"
    assert held.reason == "held:read_failed"
    assert demo._quality_with_failure_hold("right", good, 13.0).status == "good"


def test_tof_reader_parses_ascii_imu_demo_lines():
    reader = TofSerialReader("/dev/null")
    reader._parse_imu_line(b"IMU,12.5,-1.0,3.0,0.1,0.2,0.3,1.0,2.0,3.0")
    summary = reader.get_summary()

    assert summary["imu"]["status"] == "ok"
    assert summary["imu"]["heading_deg"] == 12.5
    assert summary["imu"]["roll_deg"] == -1.0
    assert summary["imu"]["pitch_deg"] == 3.0
    assert summary["imu"]["accel"] == [0.1, 0.2, 0.3]
    assert summary["imu"]["gyro"] == [1.0, 2.0, 3.0]


def test_html_page_compact_status_includes_imu_fields():
    assert 'imu_status' in HTML_PAGE
    assert 'imu_heading_deg' in HTML_PAGE
    assert 'imu_roll_deg' in HTML_PAGE
    assert 'imu_pitch_deg' in HTML_PAGE
