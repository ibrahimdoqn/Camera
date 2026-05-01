"""Background RTSP capture worker using OpenCV's FFmpeg backend.

GPU/hardware decoding is configured per-capture via ``CAP_PROP_HW_ACCELERATION``
and per-process via the ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` env var. Both knobs
are honoured by the FFmpeg backend bundled with ``opencv-python``.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


# Map a user-friendly hw-accel name (the same labels exposed in Settings) to
# the OpenCV ``VIDEO_ACCELERATION_*`` constant and the ``hwaccel`` value we
# pass to FFmpeg via the env var. ``cuda`` is the right choice for NVIDIA
# cards (RTX 30/40 series) — FFmpeg routes it through NVDEC.
_HW_ACCEL_MAP: dict[str, tuple[int, str]] = {
    # name : (cv2 hw_acceleration enum, ffmpeg hwaccel name)
    "auto":    (1, ""),         # VIDEO_ACCELERATION_ANY — pick best at runtime
    "none":    (0, ""),         # VIDEO_ACCELERATION_NONE — pure CPU
    "cuda":    (1, "cuda"),     # NVDEC via FFmpeg (NVIDIA GPUs)
    "d3d11va": (2, "d3d11va"),  # VIDEO_ACCELERATION_D3D11 (Windows DXVA 2.0)
    "dxva2":   (1, "dxva2"),    # FFmpeg-side DXVA2; OpenCV maps to ANY
}


def _resolve_hw_accel(name: str) -> tuple[int, str]:
    """Look up the OpenCV / FFmpeg hwaccel pair for ``name`` (case-insensitive)."""
    return _HW_ACCEL_MAP.get((name or "auto").lower(), _HW_ACCEL_MAP["auto"])


# Default RTSP options applied to every capture. We keep these on the worker
# rather than baking them into a single env var at process start so we can
# layer the per-stream hwaccel choice on top without losing transport tweaks.
_BASE_FFMPEG_OPTS = (
    "rtsp_transport;tcp"
    "|stimeout;5000000"
    "|max_delay;500000"
    "|buffer_size;1024000"
)


def _ffmpeg_options_for(hw_accel: str) -> str:
    """Build the ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` payload for ``hw_accel``."""
    _, ffmpeg_name = _resolve_hw_accel(hw_accel)
    if not ffmpeg_name:
        return _BASE_FFMPEG_OPTS
    # ``hwaccel`` tells FFmpeg to attempt hardware decoding for this capture.
    # ``hwaccel_output_format`` keeps the surfaces in GPU memory until the
    # final RGB conversion, which is what actually relieves CPU pressure on
    # H.264/H.265 RTSP streams.
    extras = f"hwaccel;{ffmpeg_name}|hwaccel_output_format;{ffmpeg_name}"
    return f"{_BASE_FFMPEG_OPTS}|{extras}"


class StreamWorker(QObject):
    """Reads frames from an RTSP URL and emits them as numpy arrays (BGR)."""

    frame_ready = pyqtSignal(np.ndarray)
    status_changed = pyqtSignal(str)  # "connecting" | "online" | "offline" | "error"
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, url: str, target_fps: int = 20,
                 reconnect_delay: float = 3.0,
                 hw_accel: str = "auto") -> None:
        super().__init__()
        self._url = url
        self._target_fps = max(1, target_fps)
        self._reconnect_delay = reconnect_delay
        self._hw_accel = hw_accel or "auto"
        self._running = False

    def update_url(self, url: str) -> None:
        self._url = url

    def update_target_fps(self, fps: int) -> None:
        self._target_fps = max(1, int(fps))

    def update_hw_accel(self, hw_accel: str) -> None:
        self._hw_accel = hw_accel or "auto"

    def stop(self) -> None:
        self._running = False

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        """Open the RTSP stream with the configured hardware acceleration.

        FFmpeg reads ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` once, when the capture
        is constructed, so we set it just before calling ``VideoCapture``. The
        OpenCV-level ``CAP_PROP_HW_ACCELERATION`` property is the second lever
        — together they give us the best chance of routing the decode through
        the GPU regardless of which path the bundled FFmpeg supports.
        """
        accel_enum, _ = _resolve_hw_accel(self._hw_accel)
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _ffmpeg_options_for(self._hw_accel)
        try:
            params = [
                cv2.CAP_PROP_HW_ACCELERATION, accel_enum,
                cv2.CAP_PROP_HW_DEVICE, 0,
            ]
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG, params)
        except (TypeError, AttributeError):
            # Older OpenCV builds don't accept the params overload — fall
            # back to the 2-arg form. The env-var hwaccel hint above still
            # applies, so we don't lose GPU decoding entirely.
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        return cap

    def run(self) -> None:
        self._running = True

        while self._running:
            self.status_changed.emit("connecting")
            cap = self._open_capture()
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except cv2.error:
                pass

            if cap is None or not cap.isOpened():
                self.status_changed.emit("offline")
                self.error.emit("Bağlantı kurulamadı")
                if cap is not None:
                    cap.release()
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
