"""Background RTSP capture worker using OpenCV's FFmpeg backend."""
from __future__ import annotations

import time

import cv2
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


class StreamWorker(QObject):
    """Reads frames from an RTSP URL and emits them as numpy arrays (BGR)."""

    frame_ready = pyqtSignal(np.ndarray)
    status_changed = pyqtSignal(str)  # "connecting" | "online" | "offline" | "error"
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, url: str, target_fps: int = 20, reconnect_delay: float = 3.0) -> None:
        super().__init__()
        self._url = url
        self._target_fps = max(1, target_fps)
        self._reconnect_delay = reconnect_delay
        self._running = False

    def update_url(self, url: str) -> None:
        self._url = url

    def update_target_fps(self, fps: int) -> None:
        self._target_fps = max(1, int(fps))

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True

        while self._running:
            self.status_changed.emit("connecting")
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except cv2.error:
                pass

            if not cap.isOpened():
                self.status_changed.emit("offline")
                self.error.emit("Bağlantı kurulamadı")
                self._sleep_interruptible(self._reconnect_delay)
                continue

            self.status_changed.emit("online")
            last_emit = 0.0
            consecutive_failures = 0

            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures > 30:
                        break
                    time.sleep(0.05)
                    continue
                consecutive_failures = 0

                now = time.monotonic()
                # Re-read each iteration so a settings change applies immediately.
                interval = 1.0 / max(1, self._target_fps)
                if now - last_emit >= interval:
                    last_emit = now
                    self.frame_ready.emit(frame)

            cap.release()
            if self._running:
                self.status_changed.emit("offline")
                self._sleep_interruptible(self._reconnect_delay)

        self.status_changed.emit("offline")
        self.finished.emit()

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(0.1)
