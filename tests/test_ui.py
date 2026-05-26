import http.client
import threading
import time

import pytest

from aria.ui import (
    DemoStatus,
    OverlayRenderer,
    WebDemo,
    _SharedState,
    _encode_jpeg,
    _make_handler,
)


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
