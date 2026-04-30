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
from .stream_worker import StreamWorker


STATUS_COLORS = {
    "connecting": "#ffd60a",
    "online":     "#30d158",
    "offline":    "#ff453a",
    "error":      "#ff453a",
    "idle":       "#9a9aa0",
}


class CameraTile(QWidget):
    """Renders one camera. Click selects, double-click toggles maximize."""

    clicked = pyqtSignal(str)         # single click → select
    double_clicked = pyqtSignal(str)  # double click → toggle maximize

    def __init__(self, camera: Camera, target_fps: int = 20, reconnect_delay: float = 3.0,
                 show_overlay: bool = True, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.camera = camera
        self._target_fps = target_fps
        self._reconnect_delay = reconnect_delay
        self._show_overlay = show_overlay
        self._selected = False

        self._pixmap: Optional[QPixmap] = None
        self._status: str = "idle"
        self._last_error: str = ""

        # Zoom/pan state. zoom = 1.0 fits the widget.
        self._zoom: float = 1.0
        self._pan = QPointF(0.0, 0.0)  # in widget pixels (offset of image center)

        self._worker: Optional[StreamWorker] = None
        self._thread: Optional[QThread] = None

        # Audio playback (lazy-init, only when enabled).
        self._audio_player = None
        self._audio_output = None

        self.setMinimumSize(QSize(240, 140))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._dragging = False
        self._drag_origin = QPointF(0.0, 0.0)
        self._pan_origin = QPointF(0.0, 0.0)

    # -- public API --

    def start(self) -> None:
        if self._thread is not None:
            return
        self._status = "connecting"
        thread = QThread()
        worker = StreamWorker(
            url=self.camera.rtsp_url,
            target_fps=self._target_fps,
            reconnect_delay=self._reconnect_delay,
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
        self._apply_audio_state()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        # Don't block the UI thread waiting for the worker — let it shut down
        # asynchronously via the finished signal.
        self._worker = None
        self._thread = None
        self._stop_audio()
        self._status = "idle"
        self.update()

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

    def set_selected(self, value: bool) -> None:
        if self._selected != value:
            self._selected = value
            self.update()

    def update_camera(self, camera: Camera) -> None:
        old_url = self.camera.rtsp_url if self.camera else ""
        old_audio = self.camera.audio_enabled if self.camera else False
        self.camera = camera
        if self._worker is not None and old_url != camera.rtsp_url:
            # Force a reconnect with the new URL. stop()/start() are
            # non-blocking now, so this is safe on the UI thread.
            self.stop()
            self.start()
        elif old_audio != camera.audio_enabled:
            self._apply_audio_state()
        self.update()

    # -- audio --

    def _apply_audio_state(self) -> None:
        if self.camera.audio_enabled and self._worker is not None:
            self._start_audio()
        else:
            self._stop_audio()

    def _start_audio(self) -> None:
        if self._audio_player is not None:
            return
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
        except Exception:
            self._audio_player = None
            self._audio_output = None

    def _stop_audio(self) -> None:
        if self._audio_player is not None:
            try:
                self._audio_player.stop()
                self._audio_player.deleteLater()
            except Exception:
                pass
            self._audio_player = None
        if self._audio_output is not None:
            try:
                self._audio_output.deleteLater()
            except Exception:
                pass
            self._audio_output = None

    # -- worker callbacks --

    def _on_frame(self, frame: np.ndarray) -> None:
        # frame is BGR.
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        image = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(image)
        self.update()

    def _on_status(self, status: str) -> None:
        self._status = status
        self.update()

    def _on_error(self, message: str) -> None:
        self._last_error = message

    # -- painting --

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        radius = 14
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Background card.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0e0e10"))
        painter.drawRoundedRect(rect, radius, radius)

        painter.setClipPath(self._rounded_path(rect, radius))

        if self._pixmap is not None and not self._pixmap.isNull():
            self._draw_video(painter, rect)
        else:
            self._draw_placeholder(painter, rect)

        painter.setClipping(False)

        # Border (highlighted when selected).
        pen = QPen(QColor("#0a84ff" if self._selected else "#2c2c2e"))
        pen.setWidth(2 if self._selected else 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        if self._show_overlay:
            self._draw_overlay(painter, rect)

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
        # Top-left: camera name with status dot.
        margin = 12
        font = QFont(painter.font())
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)

        name = self.camera.name or self.camera.host
        text_rect = painter.fontMetrics().boundingRect(name)
        chip_w = text_rect.width() + 36
        chip_h = 26
        chip = QRectF(rect.left() + margin, rect.top() + margin, chip_w, chip_h)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.drawRoundedRect(chip, 13, 13)

        dot_color = QColor(STATUS_COLORS.get(self._status, "#9a9aa0"))
        painter.setBrush(dot_color)
        painter.drawEllipse(QPointF(chip.left() + 14, chip.center().y()), 4.5, 4.5)

        painter.setPen(QColor("#f2f2f7"))
        painter.drawText(
            QRectF(chip.left() + 24, chip.top(), chip.width() - 28, chip.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            name,
        )

        # Top-right: zoom indicator if zoomed.
        if self._zoom > 1.01:
            zoom_text = f"{self._zoom:.1f}x"
            tw = painter.fontMetrics().horizontalAdvance(zoom_text) + 18
            zchip = QRectF(rect.right() - margin - tw, rect.top() + margin, tw, chip_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 140))
            painter.drawRoundedRect(zchip, 13, 13)
            painter.setPen(QColor("#f2f2f7"))
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

        scale_change = new_zoom / self._zoom

        if delta > 0:
            # Zoom in: anchor on cursor so the point under the cursor stays put.
            rect = QRectF(self.rect())
            center = rect.center()
            cursor = QPointF(event.position())
            offset = (cursor - center) - self._pan
            self._pan = (cursor - center) - offset * scale_change
        else:
            # Zoom out: scale pan toward 0 so the image re-centers smoothly.
            self._pan = QPointF(self._pan.x() * scale_change, self._pan.y() * scale_change)

        self._zoom = new_zoom
        if self._zoom <= 1.0001:
            self._zoom = 1.0
            self._pan = QPointF(0.0, 0.0)
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_origin = QPointF(event.position())
            self._pan_origin = QPointF(self._pan)
        elif event.button() == Qt.MouseButton.RightButton:
            self.reset_zoom()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging and self._zoom > 1.0:
            delta = QPointF(event.position()) - self._drag_origin
            self._pan = QPointF(self._pan_origin.x() + delta.x(), self._pan_origin.y() + delta.y())
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        moved = (QPointF(event.position()) - self._drag_origin).manhattanLength() > 4
        was_dragging = self._dragging
        self._dragging = False
        if event.button() == Qt.MouseButton.LeftButton and was_dragging and not moved:
            # Single click: select only (does NOT toggle maximize).
            self.clicked.emit(self.camera.id)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.camera.id)
        super().mouseDoubleClickEvent(event)
