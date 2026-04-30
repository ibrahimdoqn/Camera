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
    # and only reveal the main window after every camera has produced its
    # first frame (or a short timeout elapses).
    cfg = load_config()
    splash = SplashScreen(total_cameras=len(cfg.cameras))
    splash.start()
    app.processEvents()

    window = MainWindow(preloaded_config=cfg, splash=splash)
    splash.finished.connect(window.show)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
