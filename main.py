"""Tapo Camera Viewer - entry point."""
from __future__ import annotations

import os
import sys

# Force FFmpeg backend with low-latency settings before importing OpenCV.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000|max_delay;500000|buffer_size;1024000",
)

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from app.config import load_config
from app.main_window import MainWindow
from app.splash import SplashScreen
from app.styles import APP_STYLESHEET


def main() -> int:
    # High-DPI scaling is enabled by default in PyQt6; no setAttribute needed.
    app = QApplication(sys.argv)
    app.setApplicationName("Tapo Viewer")
    app.setOrganizationName("TapoViewer")
    app.setStyle("Fusion")

    # Prefer SF Pro / Inter / Segoe UI Variable for the Apple-like feel.
    preferred = ["SF Pro Display", "SF Pro Text", "Inter", "Segoe UI Variable", "Segoe UI"]
    available = set(QFontDatabase.families())
    for family in preferred:
        if family in available:
            app.setFont(QFont(family, 10))
            break

    app.setStyleSheet(APP_STYLESHEET)

    # Animated splash screen: show first, build the main window behind it,
    # and only reveal the main window after every visible camera has
    # settled (delivered its first frame or reported offline/error). Hidden
    # cameras don't have a stream worker, so they're skipped.
    cfg = load_config()
    visible_count = sum(1 for c in cfg.cameras if getattr(c, "visible", True))
    splash = SplashScreen(total_cameras=visible_count)
    splash.set_stage("Yapılandırma okunuyor")
    splash.start()
    app.processEvents()

    splash.set_stage("Pencere hazırlanıyor")
    app.processEvents()
    window = MainWindow(preloaded_config=cfg, splash=splash)
    if visible_count:
        splash.set_stage("Kameralara bağlanılıyor")
    else:
        splash.set_stage("Hazırlanıyor")
    splash.finished.connect(window.show)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
