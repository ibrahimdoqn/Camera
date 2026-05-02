"""Tapo Camera Viewer - entry point."""
from __future__ import annotations

import os
import sys

# Force FFmpeg backend with low-latency settings before importing OpenCV.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000|max_delay;500000|buffer_size;1024000",
)

from PyQt6.QtGui import QFont, QFontDatabase, QIcon
from PyQt6.QtWidgets import QApplication

from app.config import load_config
from app.main_window import MainWindow
from app.splash import SplashScreen
from app.styles import APP_STYLESHEET


def _resource_path(relative: str) -> str:
    """Resolve a bundled resource path for both dev and PyInstaller runs."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def main() -> int:
    # High-DPI scaling is enabled by default in PyQt6; no setAttribute needed.
    app = QApplication(sys.argv)
    app.setApplicationName("Tapo Viewer")
    app.setOrganizationName("TapoViewer")
    app.setStyle("Fusion")

    for icon_name in ("Tapo.ico", "Tapo.png"):
        icon_path = _resource_path(icon_name)
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TapoViewer.App")
        except Exception:
            pass

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
