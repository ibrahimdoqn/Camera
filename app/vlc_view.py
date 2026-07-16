"""libVLC-based native video embed.

Rendering is delegated to VLC through a native window handle, so the GPU
decode path is the one VLC negotiates automatically — DXVA2 / D3D11 on
Windows, VAAPI on Linux, VideoToolbox on macOS. There is no readback into
Python memory: VLC writes decoded frames directly to the surface that
Windows composes onto the screen. Compared with the opencv/ffmpeg workers
this is significantly kinder to the CPU because the frames never leave the
GPU on their way to the display.

The widget deliberately does *not* draw the tile's overlay chip on top of
the video: a native child HWND is composed above the parent's Qt paint
output, and mixing the two produces flicker on Windows. Callers should
hide the overlay (or rely on the sidebar's status dot) when this backend
is in use.
"""
from __future__ import annotations

import sys
import time
from typing import Optional

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication, QSizePolicy, QWidget


# Reconnection cadence. Kept in the same ballpark as StreamWorker's watchdog
# so a broken camera flips to "offline" in a comparable amount of time.
_WATCHDOG_S = 8.0
_RECONNECT_DELAY_S = 3.0


def _map_hw_accel(name: str) -> Optional[str]:
    """Translate the app's hw-accel labels to VLC's ``--avcodec-hw`` value.

    ``None`` means "let VLC pick" (its default is ``any``, i.e. the first
    driver that succeeds — that's what actually delivers native HW decode
    without user configuration).
    """
    name = (name or "auto").lower()
    if name == "auto":
        return None
    if name == "none":
        return "none"
    if name in ("d3d11va", "dxva2"):
        return name
    if name == "cuda":
        # ffmpeg-hw name is nvdec inside VLC's option namespace.
        return "nvdec"
    if name == "qsv":
        return "qsv"
    return None


class VLCVideoWidget(QWidget):
    """QWidget that hosts a libVLC MediaPlayer via native window embedding."""

    status_changed = pyqtSignal(str)  # "connecting" | "online" | "offline" | "error"
    first_frame = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # A native window handle is what libVLC's set_hwnd/set_xwindow needs.
        # Without WA_NativeWindow, winId() would keep returning the parent's
        # handle and VLC would render into the wrong region.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet("background:#000;")
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._url: str = ""
        self._hw_accel: str = "auto"
        self._instance = None
        self._player = None
        self._media = None
        self._first_frame_seen = False
        self._current_status = "idle"

        # A short poll loop is enough to translate VLC's is_playing() state
        # into our status signal. VLC has an event manager but the callbacks
        # fire on VLC threads, and shipping their arguments back to Qt is
        # more code than a 500 ms Qt timer.
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._poll_state)

        self._connect_started_at = 0.0
        self._reconnect_at: Optional[float] = None

    # -- public API --

    def is_usable(self) -> bool:
        """Return ``True`` if python-vlc + libvlc are importable."""
        try:
            import vlc  # type: ignore  # noqa: F401
        except Exception:
            return False
        return True

    def start(self, url: str, hw_accel: str = "auto") -> None:
        self._url = url or ""
        self._hw_accel = hw_accel or "auto"
        self._start_player()
        self._poll.start()

    def stop(self) -> None:
        self._poll.stop()
        self._stop_player()
        self._emit_status("idle")

    def set_hw_accel(self, hw_accel: str) -> None:
        new_mode = hw_accel or "auto"
        if new_mode == self._hw_accel:
            return
        self._hw_accel = new_mode
        # HW accel is decided when the libvlc Instance is constructed, so
        # we have to rebuild it. Cheap in practice — the RTSP pipeline
        # re-establishes in a couple of seconds.
        if self._url:
            self._stop_player()
            self._start_player()

    def set_url(self, url: str) -> None:
        if url == self._url:
            return
        self._url = url or ""
        if self._url:
            self._stop_player()
            self._start_player()

    def shutdown(self) -> None:
        self.stop()

    # -- internals --

    def _start_player(self) -> None:
        try:
            import vlc  # type: ignore
        except Exception as exc:
            self.error.emit(f"libVLC bulunamadı: {exc}")
            self._emit_status("error")
            return

        args = [
            "--intf", "dummy",
            "--no-osd",
            "--no-video-title-show",
            "--no-stats",
            "--quiet",
            "--rtsp-tcp",
            "--network-caching=300",
            "--live-caching=300",
            "--clock-jitter=0",
            "--clock-synchro=0",
            # Silence VLC's own subprocess-based helpers so we don't get a
            # console window flashing on Windows.
            "--no-lua",
        ]
        mode = _map_hw_accel(self._hw_accel)
        if mode is not None:
            args.append(f"--avcodec-hw={mode}")
        # Audio is handled elsewhere (or not at all if the user muted it).
        # ``--no-audio`` avoids two backends fighting over the same speaker.
        args.append("--no-audio")

        try:
            self._instance = vlc.Instance(*args)
            if self._instance is None:
                raise RuntimeError("vlc.Instance returned None")
            self._player = self._instance.media_player_new()
            self._media = self._instance.media_new(self._url)
            self._player.set_media(self._media)
        except Exception as exc:
            self.error.emit(f"VLC oynatıcı hazırlanamadı: {exc}")
            self._emit_status("error")
            return

        self._embed_native_window()

        self._first_frame_seen = False
        self._connect_started_at = time.monotonic()
        self._reconnect_at = None
        try:
            self._player.play()
        except Exception as exc:
            self.error.emit(f"VLC oynatma başlatılamadı: {exc}")
            self._emit_status("error")
            return
        self._emit_status("connecting")

    def _embed_native_window(self) -> None:
        if self._player is None:
            return
        try:
            handle = int(self.winId())
        except Exception:
            handle = 0
        if not handle:
            return
        try:
            if sys.platform.startswith("win"):
                self._player.set_hwnd(handle)
            elif sys.platform == "darwin":
                self._player.set_nsobject(handle)
            else:
                self._player.set_xwindow(handle)
        except Exception:
            # Non-fatal: libVLC will fall back to its own popup window,
            # which is undesirable but keeps the app alive.
            pass

    def _stop_player(self) -> None:
        # We intentionally do not call ``release()`` on the instance/player
        # here — libVLC's release path re-enters Python via callbacks and
        # has been observed to crash when fired from a Qt event handler.
        # Dropping our references lets the GC finish teardown at a quiet
        # moment; the underlying sockets close as soon as ``stop()`` runs.
        player = self._player
        self._player = None
        self._media = None
        self._instance = None
        self._first_frame_seen = False
        self._reconnect_at = None
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass

    def _poll_state(self) -> None:
        if self._player is None:
            # Waiting to reconnect after a failure?
            if self._reconnect_at is not None and time.monotonic() >= self._reconnect_at:
                self._start_player()
            return
        try:
            state = self._player.get_state()
        except Exception:
            state = None
        try:
            import vlc  # type: ignore
        except Exception:
            return

        # Map VLC states onto our four-status vocabulary.
        if state in (vlc.State.Opening, vlc.State.Buffering, vlc.State.NothingSpecial):
            if not self._first_frame_seen:
                # Guard against the RTSP source that never delivers a frame:
                # after WATCHDOG_S in "connecting" we tear it down.
                if time.monotonic() - self._connect_started_at > _WATCHDOG_S:
                    self._schedule_reconnect("Bağlantı zaman aşımı")
        elif state == vlc.State.Playing:
            # ``video_get_width`` returns 0 until the first frame is
            # actually decoded, so we use it as our "online" trigger.
            has_video = False
            try:
                has_video = self._player.video_get_width() > 0
            except Exception:
                has_video = True
            if has_video:
                if not self._first_frame_seen:
                    self._first_frame_seen = True
                    self.first_frame.emit()
                self._emit_status("online")
            else:
                self._emit_status("connecting")
                if time.monotonic() - self._connect_started_at > _WATCHDOG_S:
                    self._schedule_reconnect("Video yok")
        elif state in (vlc.State.Error, vlc.State.Ended):
            self._schedule_reconnect("Akış sonlandı")
        elif state == vlc.State.Paused:
            self._emit_status("connecting")

    def _schedule_reconnect(self, reason: str) -> None:
        self._stop_player()
        self._emit_status("offline")
        self._reconnect_at = time.monotonic() + _RECONNECT_DELAY_S
        self.error.emit(reason)

    def _emit_status(self, status: str) -> None:
        if status == self._current_status:
            return
        self._current_status = status
        self.status_changed.emit(status)

    # -- paint fallback --

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        # VLC draws directly to the native surface after the first frame,
        # but before that the widget is still a plain Qt window — paint a
        # black rectangle so we don't briefly show whatever was underneath.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))

    # -- forward mouse + wheel events to the tile ----------------------
    # A native HWND swallows Qt's default event propagation on Windows,
    # so a click on the video would never reach the parent CameraTile
    # (breaking "click to select" and "double-click to maximize"). We
    # forward each event manually by translating its position into the
    # parent's coordinate system and re-posting it. Same trick for the
    # wheel, so cursor-anchored zoom keeps working.

    def _forward_mouse(self, event: QMouseEvent) -> None:
        parent = self.parentWidget()
        if parent is None:
            event.ignore()
            return
        pos_in_parent = self.mapToParent(event.position().toPoint())
        forwarded = QMouseEvent(
            event.type(),
            QPointF(pos_in_parent),
            event.globalPosition(),
            event.button(),
            event.buttons(),
            event.modifiers(),
        )
        QApplication.sendEvent(parent, forwarded)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._forward_mouse(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._forward_mouse(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._forward_mouse(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._forward_mouse(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        parent = self.parentWidget()
        if parent is None:
            event.ignore()
            return
        pos_in_parent = self.mapToParent(event.position().toPoint())
        forwarded = QWheelEvent(
            QPointF(pos_in_parent),
            event.globalPosition(),
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
            event.source(),
        )
        QApplication.sendEvent(parent, forwarded)
        event.accept()
