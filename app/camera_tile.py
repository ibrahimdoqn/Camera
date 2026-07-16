"""A single camera tile: video display, status overlay, mouse-wheel zoom & pan."""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .config import Camera
from .stream_worker import FFmpegSubprocessWorker, StreamWorker
from .vlc_view import VLCVideoWidget


# When a tile is stopped, we hand the worker + QThread off to Qt's
# ownership so PyQt's sip layer doesn't destroy the C++ ``QThread``
# while ``run()`` is still on the stack. Qt aborts the process at that
# point with ``QThread: Destroyed while thread is still running``
# (Windows reports it as ``c0000409 / FAST_FAIL_FATAL_APP_EXIT`` inside
# Qt6Core.dll). The fallback graveyard set keeps a Python reference if
# ``sip`` is somehow unavailable, so the wrapper isn't garbage-collected
# either.
try:
    from PyQt6 import sip  # type: ignore
except ImportError:  # pragma: no cover - sip ships with PyQt6
    sip = None  # type: ignore

_THREAD_GRAVEYARD: set = set()


def _bury_running_thread(worker: object, thread: object) -> None:
    """Make ``worker`` and ``thread`` survive their tile being deleted.

    Without this, ``CameraTile.stop()`` clearing ``self._worker`` /
    ``self._thread`` (followed by the tile's own ``deleteLater``) drops
    the last Python references to the still-running worker thread.
    PyQt's sip then calls ``~QThread()`` on a thread whose event loop
    hasn't exited yet — Qt treats that as a fatal programming error and
    aborts via ``__fastfail`` (``c0000409`` in the Windows error
    report). We work around it by transferring C++ ownership to Qt so
    Python GC of the wrapper no longer touches the C++ object; the
    existing ``worker.finished → deleteLater`` chain destroys both
    objects safely once ``run()`` actually returns.
    """
    if sip is not None:
        for obj in (worker, thread):
            try:
                sip.transferto(obj, None)
            except (TypeError, ValueError):
                # transferto raises if the object already has a Qt
                # parent — that's fine, the parent protects it just as
                # well as transferto would.
                pass
        return
    # sip missing (shouldn't happen with a normal PyQt6 install). Fall
    # back to a module-level reference set so the Python wrapper isn't
    # GC'd. We never remove from this set because doing so would re-
    # introduce the same race; the leak is bounded by user actions and
    # cleared on app exit.
    _THREAD_GRAVEYARD.add((worker, thread))


STATUS_COLORS = {
    "connecting": "#ffd60a",
    "online":     "#30d158",
    "offline":    "#ff453a",
    "error":      "#ff453a",
    "idle":       "#9a9aa0",
}

# Pixels of cursor travel before a press becomes a drag. Below this, the
# gesture is treated as a click — the image must not pan during the click.
DRAG_THRESHOLD = 6


class CameraTile(QWidget):
    """Renders one camera. Click selects, double-click toggles maximize."""

    clicked = pyqtSignal(str)         # single click → select
    double_clicked = pyqtSignal(str)  # double click → toggle maximize
    first_frame = pyqtSignal(str)     # camera_id, fired once when first
                                      # frame arrives (used by the splash)
    status_changed = pyqtSignal(str, str)  # camera_id, status

    def __init__(self, camera: Camera, target_fps: int = 20, reconnect_delay: float = 3.0,
                 show_overlay: bool = True, hw_accel: str = "auto",
                 playback_backend: str = "opencv",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.camera = camera
        self._target_fps = target_fps
        self._reconnect_delay = reconnect_delay
        self._show_overlay = show_overlay
        self._hw_accel = hw_accel or "auto"
        self._playback_backend = (playback_backend or "opencv").lower()
        self._selected = False

        self._pixmap: Optional[QPixmap] = None
        self._status: str = "idle"
        self._last_error: str = ""
        self._emitted_first_frame: bool = False

        # Zoom/pan state. zoom = 1.0 fits the widget.
        self._zoom: float = 1.0
        self._pan = QPointF(0.0, 0.0)  # in widget pixels (offset of image center)

        self._worker = None  # StreamWorker | FFmpegSubprocessWorker | None
        self._thread: Optional[QThread] = None
        # Only populated when playback_backend == "vlc". The widget owns
        # its own libVLC MediaPlayer and paints directly to a native HWND.
        self._vlc_widget: Optional[VLCVideoWidget] = None

        # Audio playback (lazy-init, only when enabled).
        # Backend can be either libVLC (preferred — actually supports RTSP
        # audio) or Qt's QMediaPlayer (fallback).
        self._audio_player = None
        self._audio_output = None
        self._audio_backend: Optional[str] = None

        self.setMinimumSize(QSize(240, 140))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._dragging = False
        self._press_pos = QPointF(0.0, 0.0)
        self._pan_origin = QPointF(0.0, 0.0)

    # -- public API --

    def start(self) -> None:
        if self._thread is not None or self._vlc_widget is not None:
            return
        self._status = "connecting"
        if self._playback_backend == "vlc":
            self._start_vlc_widget()
        else:
            self._start_worker()
        self._apply_audio_state()

    def _start_worker(self) -> None:
        """Spin up a frame-emitting worker (OpenCV or FFmpeg subprocess).

        Both backends share the same signal contract; the tile paints the
        frames itself via ``_on_frame`` so overlay + zoom/pan keep working.
        """
        thread = QThread()
        worker_cls = (
            FFmpegSubprocessWorker
            if self._playback_backend == "ffmpeg"
            else StreamWorker
        )
        worker = worker_cls(
            url=self.camera.rtsp_url,
            target_fps=self._target_fps,
            reconnect_delay=self._reconnect_delay,
            hw_accel=self._hw_accel,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.frame_ready.connect(self._on_frame)
        worker.status_changed.connect(self._on_status)
        worker.error.connect(self._on_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        self._worker = worker
        self._thread = thread

    def _start_vlc_widget(self) -> None:
        """Attach a libVLC-backed video surface as a child widget."""
        vlc_widget = VLCVideoWidget(self)
        vlc_widget.status_changed.connect(self._on_status)
        vlc_widget.error.connect(self._on_error)
        vlc_widget.first_frame.connect(self._on_vlc_first_frame)
        vlc_widget.setGeometry(self._vlc_child_rect())
        vlc_widget.show()
        vlc_widget.raise_()
        vlc_widget.start(self.camera.rtsp_url, self._hw_accel)
        self._vlc_widget = vlc_widget

    def _vlc_child_rect(self):
        """Rectangle the VLC child covers — leaves the rounded border showing."""
        # Inset by the same amount we round the border so the black native
        # HWND doesn't clip through the tile's corner radius.
        margin = 2
        return self.rect().adjusted(margin, margin, -margin, -margin)

    def _detach_worker_signals(self) -> None:
        """Disconnect the tile's slots from the live worker.

        The worker keeps running until its capture loop notices
        ``_running=False`` (cap.read can hold the thread for several
        seconds), and during that window it can still emit
        ``frame_ready`` / ``status_changed`` / ``error``. If the tile is
        deleted in the meantime — which is exactly what happens when the
        user hides the camera or changes hardware acceleration — those
        queued signals would be dispatched to a half-deleted Python
        wrapper and crash the process. Disconnecting before we drop the
        Python reference makes the queue harmless: the worker's signals
        simply have nowhere left to go.
        """
        worker = self._worker
        if worker is None:
            return
        for sig, slot in (
            (worker.frame_ready, self._on_frame),
            (worker.status_changed, self._on_status),
            (worker.error, self._on_error),
        ):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                # Already disconnected, or the underlying C++ object is gone.
                pass

    def stop(self) -> None:
        if self._worker is not None and self._thread is not None:
            self._detach_worker_signals()
            self._worker.stop()
            # Hand C++ ownership to Qt before dropping our Python
            # references. Otherwise ~QThread() runs while ``run()`` is
            # still in cap.read() and Qt fast-fails the process.
            _bury_running_thread(self._worker, self._thread)
        # Don't block the UI thread waiting for the worker — let it shut down
        # asynchronously via the finished signal. Signals are already
        # detached, so the in-flight worker can run to completion safely.
        self._worker = None
        self._thread = None
        self._teardown_vlc_widget()
        self._stop_audio()
        self._status = "idle"
        self._pixmap = None
        self.update()

    def stop_and_wait(self, timeout_ms: int = 1500) -> None:
        """Block briefly so the worker thread can exit cleanly. Use on close."""
        thread = self._thread
        worker = self._worker
        if worker is not None:
            self._detach_worker_signals()
            worker.stop()
        self._worker = None
        self._thread = None
        self._teardown_vlc_widget()
        self._stop_audio()
        self._status = "idle"
        if thread is not None:
            thread.quit()
            if not thread.wait(timeout_ms) and worker is not None:
                # Thread refused to exit in time. Don't let sip destroy
                # the C++ QThread out from under it — bury it instead so
                # Qt's deleteLater chain (or app shutdown) handles it.
                _bury_running_thread(worker, thread)

    def _teardown_vlc_widget(self) -> None:
        if self._vlc_widget is None:
            return
        widget = self._vlc_widget
        self._vlc_widget = None
        for sig, slot in (
            (widget.status_changed, self._on_status),
            (widget.error, self._on_error),
            (widget.first_frame, self._on_vlc_first_frame),
        ):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        try:
            widget.shutdown()
        except Exception:
            pass
        widget.hide()
        widget.setParent(None)
        widget.deleteLater()

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def set_show_overlay(self, value: bool) -> None:
        self._show_overlay = value
        self.update()

    def set_target_fps(self, fps: int) -> None:
        self._target_fps = max(1, int(fps))
        if self._worker is not None:
            self._worker.update_target_fps(self._target_fps)

    def set_hw_accel(self, hw_accel: str) -> None:
        """Change the hardware-decoding mode. Forces a reconnect because
        FFmpeg picks the decoder when ``VideoCapture`` is constructed and
        we can't switch it on a live capture."""
        new_mode = hw_accel or "auto"
        if new_mode == self._hw_accel:
            return
        self._hw_accel = new_mode
        if self._vlc_widget is not None:
            self._vlc_widget.set_hw_accel(new_mode)
        elif self._thread is not None:
            self.stop()
            self.start()

    def set_playback_backend(self, backend: str) -> None:
        """Switch playback engine. Always forces a full teardown-and-restart
        because the widget hierarchy differs between the frame-based
        backends (opencv/ffmpeg) and the native VLC embed."""
        new_backend = (backend or "opencv").lower()
        if new_backend == self._playback_backend:
            return
        was_running = self._thread is not None or self._vlc_widget is not None
        self._playback_backend = new_backend
        if was_running:
            self.stop()
            self.start()

    def set_selected(self, value: bool) -> None:
        if self._selected != value:
            self._selected = value
            self.update()

    def update_camera(self, camera: Camera) -> None:
        old_url = self.camera.rtsp_url if self.camera else ""
        old_audio = self.camera.audio_enabled if self.camera else False
        self.camera = camera
        url_changed = old_url != camera.rtsp_url
        if url_changed and (self._worker is not None or self._vlc_widget is not None):
            # Force a reconnect with the new URL. stop()/start() are
            # non-blocking now, so this is safe on the UI thread.
            self.stop()
            self.start()
        elif old_audio != camera.audio_enabled:
            self._apply_audio_state()
        self.update()

    # -- audio --

    def _apply_audio_state(self) -> None:
        has_stream = self._worker is not None or self._vlc_widget is not None
        if self.camera.audio_enabled and has_stream:
            self._start_audio()
        else:
            self._stop_audio()

    def _start_audio(self) -> None:
        """Play RTSP audio.

        Qt's :class:`QMediaPlayer` (Windows Media Foundation backend) does
        not support RTSP, so the actual audio you hear in tools like
        StreamShow / VLC is delivered by libVLC. We mirror that: if
        ``python-vlc`` is installed, use it as the audio backend; only fall
        back to ``QMediaPlayer`` when VLC is not available (it usually fails
        for RTSP, but we keep the fallback so nothing crashes).
        """
        if self._audio_player is not None:
            return

        # 1) Preferred path: libVLC.
        try:
            import vlc  # type: ignore
        except ImportError:
            vlc = None  # type: ignore

        if vlc is not None:
            try:
                # No video — we render the picture ourselves via OpenCV; VLC
                # is here strictly for the audio track. ``--network-caching``
                # mirrors typical low-latency RTSP defaults.
                instance = vlc.Instance(
                    "--no-video",
                    "--network-caching=300",
                    "--rtsp-tcp",
                    "--quiet",
                )
                player = instance.media_player_new()
                media = instance.media_new(self.camera.rtsp_url)
                player.set_media(media)
                player.audio_set_volume(100)
                player.play()
                # Keep a reference to the instance so it isn't GC'd before
                # the player.
                self._audio_player = player
                self._audio_output = instance
                self._audio_backend = "vlc"
                return
            except Exception:
                self._audio_player = None
                self._audio_output = None

        # 2) Fallback: QMediaPlayer (rarely works with RTSP but harmless).
        try:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return
        try:
            player = QMediaPlayer(self)
            output = QAudioOutput(self)
            player.setAudioOutput(output)
            player.setSource(QUrl(self.camera.rtsp_url))
            output.setVolume(1.0)
            player.play()
            self._audio_player = player
            self._audio_output = output
            self._audio_backend = "qt"
        except Exception:
            self._audio_player = None
            self._audio_output = None
            self._audio_backend = None

    def _stop_audio(self) -> None:
        # libVLC's release() can re-enter Python via internal callbacks and
        # has been observed to crash the process when fired from inside a
        # QPushButton click handler (which is what happens on the
        # "hide camera" path). We deliberately *don't* call release() here:
        # we just stop playback and drop our Python references, letting
        # the GC tear the libVLC objects down out of the click stack.
        # Every step is guarded so a misbehaving backend never propagates
        # an exception up into the UI's tear-down sequence.
        backend = getattr(self, "_audio_backend", None)
        if self._audio_player is not None:
            try:
                self._audio_player.stop()
            except Exception:
                pass
            if backend != "vlc":
                try:
                    self._audio_player.deleteLater()
                except Exception:
                    pass
            self._audio_player = None
        if self._audio_output is not None:
            if backend != "vlc":
                try:
                    self._audio_output.deleteLater()
                except Exception:
                    pass
            self._audio_output = None
        self._audio_backend = None

    # -- worker callbacks --

    def _on_frame(self, frame: np.ndarray) -> None:
        # frame is BGR.
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        image = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(image)
        if not self._emitted_first_frame:
            self._emitted_first_frame = True
            self.first_frame.emit(self.camera.id)
        self.update()

    def _on_status(self, status: str) -> None:
        if self._status != status:
            self._status = status
            self.status_changed.emit(self.camera.id, status)
        self.update()

    def _on_error(self, message: str) -> None:
        self._last_error = message

    def _on_vlc_first_frame(self) -> None:
        if not self._emitted_first_frame:
            self._emitted_first_frame = True
            self.first_frame.emit(self.camera.id)
        # No pixmap to paint — VLC writes straight to the child HWND —
        # but we still repaint so the placeholder text disappears.
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._vlc_widget is not None:
            self._vlc_widget.setGeometry(self._vlc_child_rect())

    # -- painting --

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        radius = 14
        # Inset the rect by half the (eventual) pen width so the border stays
        # entirely inside the widget's geometry — otherwise the 2 px selection
        # outline bleeds outside the rounded corners and clips against the
        # neighbouring tile.
        pen_width = 2 if self._selected else 1
        inset = pen_width / 2.0
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        inner_radius = radius - inset

        # Background card.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0e0e10"))
        painter.drawRoundedRect(rect, inner_radius, inner_radius)

        painter.setClipPath(self._rounded_path(rect, inner_radius))

        if self._vlc_widget is not None:
            # VLC paints straight to the child native HWND — anything we
            # draw here would either be covered by the native surface
            # (Windows/macOS) or flicker against it (Linux). Fill the
            # backdrop black so the placeholder text goes away as soon as
            # the child widget is shown.
            painter.fillRect(rect, QColor("#000000"))
        elif self._pixmap is not None and not self._pixmap.isNull():
            self._draw_video(painter, rect)
        else:
            self._draw_placeholder(painter, rect)

        if self._show_overlay and self._vlc_widget is None:
            # Draw the overlay while still clipped so the chip can never
            # extend past the rounded corners.
            self._draw_overlay(painter, rect)

        painter.setClipping(False)

        # Border (highlighted when selected).
        pen = QPen(QColor("#0a84ff" if self._selected else "#2c2c2e"))
        pen.setWidth(pen_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, inner_radius, inner_radius)

    def _rounded_path(self, rect: QRectF, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def _draw_video(self, painter: QPainter, rect: QRectF) -> None:
        assert self._pixmap is not None
        pix = self._pixmap
        pw, ph = pix.width(), pix.height()
        if pw == 0 or ph == 0:
            return

        # Fit to widget while preserving aspect ratio (scale = 1.0).
        scale_fit = min(rect.width() / pw, rect.height() / ph)
        scale = scale_fit * self._zoom

        draw_w = pw * scale
        draw_h = ph * scale

        # Center + pan.
        cx = rect.center().x() + self._pan.x()
        cy = rect.center().y() + self._pan.y()

        # If zoom > 1, clamp pan so the image still covers the visible area.
        if self._zoom > 1.0:
            min_x = rect.right() - draw_w / 2
            max_x = rect.left() + draw_w / 2
            min_y = rect.bottom() - draw_h / 2
            max_y = rect.top() + draw_h / 2
            cx = max(min(cx, max_x), min_x)
            cy = max(min(cy, max_y), min_y)
            self._pan = QPointF(cx - rect.center().x(), cy - rect.center().y())

        target = QRectF(cx - draw_w / 2, cy - draw_h / 2, draw_w, draw_h)
        painter.fillRect(rect, QColor("#000000"))
        painter.drawPixmap(target, pix, QRectF(0, 0, pw, ph))

    def _draw_placeholder(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#0e0e10"))
        painter.setPen(QColor("#6a6a70"))
        font = QFont(painter.font())
        font.setPointSize(13)
        painter.setFont(font)
        msg = {
            "connecting": "Bağlanıyor...",
            "offline": "Bağlantı yok",
            "error": "Hata",
            "idle": "Bekleniyor",
        }.get(self._status, "...")
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, msg)

    def _draw_overlay(self, painter: QPainter, rect: QRectF) -> None:
        # Top-left: camera name with status dot. Pull the chip in past the
        # rounded corner radius so it never sits on the curve. When the tile
        # is selected (blue border), the chip is enlarged and given a subtle
        # white halo so the name and status dot stay clearly legible.
        margin = 18 if not self._selected else 14
        font = QFont(painter.font())
        font.setPointSize(13 if self._selected else 12)
        font.setWeight(QFont.Weight.Bold if self._selected else QFont.Weight.DemiBold)
        painter.setFont(font)

        name = self.camera.name or self.camera.host or "Kamera"
        text_w = painter.fontMetrics().horizontalAdvance(name)
        chip_h = 38 if self._selected else 34
        dot_d = 14 if self._selected else 12
        # left padding | dot | gap | text | right padding
        chip_w = 16 + dot_d + 10 + text_w + 16
        max_w = max(60.0, rect.width() - 2 * margin)
        chip_w = min(chip_w, max_w)
        chip = QRectF(rect.left() + margin, rect.top() + margin, chip_w, chip_h)

        # Solid pill so the white text stays legible regardless of the
        # underlying frame. When selected, a subtle white halo keeps the
        # chip distinct from the blue border behind it.
        if self._selected:
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 245 if self._selected else 230))
        painter.drawRoundedRect(chip, chip_h / 2, chip_h / 2)

        dot_color = QColor(STATUS_COLORS.get(self._status, "#9a9aa0"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_color)
        dot_cx = chip.left() + 16 + dot_d / 2
        painter.drawEllipse(QPointF(dot_cx, chip.center().y()), dot_d / 2, dot_d / 2)
        # White halo around the dot when selected so it stays vivid even on
        # top of the blue selection border.
        if self._selected:
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(dot_cx, chip.center().y()),
                                dot_d / 2 + 1.5, dot_d / 2 + 1.5)

        painter.setPen(QColor("#ffffff"))
        text_left = dot_cx + dot_d / 2 + 10
        text_right = chip.right() - 16
        painter.drawText(
            QRectF(text_left, chip.top(), max(0.0, text_right - text_left), chip.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            name,
        )

        # Top-right: zoom indicator if zoomed.
        if self._zoom > 1.01:
            zoom_text = f"{self._zoom:.1f}×"
            tw = painter.fontMetrics().horizontalAdvance(zoom_text) + 22
            zchip = QRectF(rect.right() - margin - tw, rect.top() + margin, tw, chip_h)
            if self._selected:
                painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 245 if self._selected else 230))
            painter.drawRoundedRect(zchip, chip_h / 2, chip_h / 2)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(zchip, Qt.AlignmentFlag.AlignCenter, zoom_text)

    # -- input --

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._pixmap is None:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_zoom = max(1.0, min(8.0, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-3:
            return

        # Zoom around the cursor: keep the image point currently under the
        # cursor pinned to the same screen position after the zoom change.
        rect_center = QPointF(self.rect().center())
        cursor = QPointF(event.position())
        f = new_zoom / self._zoom
        # new_pan = (1 - f) * (cursor - rect_center) + f * old_pan
        new_pan_x = (1.0 - f) * (cursor.x() - rect_center.x()) + f * self._pan.x()
        new_pan_y = (1.0 - f) * (cursor.y() - rect_center.y()) + f * self._pan.y()

        self._zoom = new_zoom
        if self._zoom <= 1.0001:
            self._zoom = 1.0
            self._pan = QPointF(0.0, 0.0)
        else:
            self._pan = QPointF(new_pan_x, new_pan_y)
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            # Don't enter drag mode yet — wait until the cursor actually moves.
            self._press_pos = QPointF(event.position())
            self._pan_origin = QPointF(self._pan)
            self._dragging = False
        elif event.button() == Qt.MouseButton.RightButton:
            self.reset_zoom()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._zoom <= 1.0:
            return
        delta = QPointF(event.position()) - self._press_pos
        if not self._dragging:
            if delta.manhattanLength() <= DRAG_THRESHOLD:
                return
            self._dragging = True
        self._pan = QPointF(self._pan_origin.x() + delta.x(),
                            self._pan_origin.y() + delta.y())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            self._dragging = False
            if not was_dragging:
                # Treat as a click: just select; don't maximize.
                self.clicked.emit(self.camera.id)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.camera.id)
        super().mouseDoubleClickEvent(event)
