"""Optional local Qt UI for ARIA v0 HDMI/display demos."""

from __future__ import annotations

from typing import Any

from .ui import WebDemo


def _import_qt() -> tuple[Any, Any, Any]:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
        return QtCore, QtGui, QtWidgets
    except Exception:
        from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
        return QtCore, QtGui, QtWidgets


class QtDemo:
    """Display the shared ARIA demo pipeline in a local Qt window.

    Qt is optional. If neither PySide6 nor PyQt5 is installed the constructor
    raises a clear RuntimeError; the web UI remains usable without Qt.
    """

    def __init__(self, pipeline: WebDemo, title: str = "ARIA v0 Demo") -> None:
        try:
            self.QtCore, self.QtGui, self.QtWidgets = _import_qt()
        except Exception as exc:  # pragma: no cover - target environment dependent
            raise RuntimeError("Qt UI requires PySide6 or PyQt5 on the Raspberry Pi desktop environment") from exc
        self.pipeline = pipeline
        self.title = title

    def run(self) -> int:  # pragma: no cover - GUI integration exercised on aria-core
        app = self.QtWidgets.QApplication.instance() or self.QtWidgets.QApplication([])
        window = self.QtWidgets.QWidget()
        window.setWindowTitle(self.title)
        layout = self.QtWidgets.QVBoxLayout(window)
        image_label = self.QtWidgets.QLabel("Starting ARIA demo...")
        image_label.setAlignment(self.QtCore.Qt.AlignCenter)
        status_label = self.QtWidgets.QLabel("")
        layout.addWidget(image_label)
        layout.addWidget(status_label)
        window.resize(960, 640)
        window.show()

        self.pipeline.start()

        def tick() -> None:
            self.pipeline.update_once()
            jpeg, status = self.pipeline._state.get()
            status_label.setText(
                f"camera={status.camera} detector={status.detector} tof={status.tof_valid_zones} "
                f"fps={status.fps:.1f} alert={status.alert} risk={status.risk}"
            )
            if jpeg:
                pixmap = self.QtGui.QPixmap()
                pixmap.loadFromData(jpeg, "JPG")
                image_label.setPixmap(
                    pixmap.scaled(image_label.size(), self.QtCore.Qt.KeepAspectRatio, self.QtCore.Qt.SmoothTransformation)
                )

        timer = self.QtCore.QTimer()
        timer.timeout.connect(tick)
        timer.start(max(1, int(self.pipeline.stream_interval * 1000)))
        try:
            return int(app.exec())
        finally:
            timer.stop()
            self.pipeline.stop()
