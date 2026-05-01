"""Animated startup splash screen.

A frameless, rounded, centred widget with a soft fade-in/fade-out and a
Windows 11-style sweeping arc (the "progress ring" pattern). The splash is
responsible for keeping itself on screen long enough for cameras to
connect: callers can either tell it how many cameras to wait for and
report when each one delivers its first frame
(:meth:`mark_camera_ready`) or simply let the timeout expire.

Notes:
* The translucent shadow used to be done with ``QGraphicsDropShadowEffect``
  on a translucent top-level window. On Windows that combination triggers
  ``UpdateLayeredWindowIndirect failed`` because the dirty rectangle ends
  up larger than the window with negative offsets. We now paint the
  shadow ourselves into a larger, transparent canvas so the dirty
  rectangle always fits inside the widget.
"""
from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import (
    Qt,
    QPointF,
    QRectF,
    QPropertyAnimation,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QWidget


# Padding around the card itself, used as the room for the painted shadow.
SHADOW_MARGIN = 24
CARD_W = 440
CARD_H = 260


class SplashScreen(QWidget):
    """Branded loading screen displayed before the main window appears."""

    finished = pyqtSignal()

    # How long we are willing to wait for cameras to connect, even if
    # some never produce a frame. Keeps the splash from getting stuck.
    MAX_LIFETIME_MS = 6000
    MIN_LIFETIME_MS = 900

    def __init__(self, total_cameras: int = 0,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.SplashScreen
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Make room for the painted drop shadow so we never have to resize
        # outside the widget — the layered-window paint path on Windows
        # rejects dirty rectangles with negative offsets.
        self.setFixedSize(CARD_W + SHADOW_MARGIN * 2,
                          CARD_H + SHADOW_MARGIN * 2)

        self._total = max(0, total_cameras)
        self._ready_ids: set[str] = set()
        self._message = self._format_progress()
        self._stage = "Başlatılıyor"
        self._angle = 0.0

        # Centre on the primary screen.
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.center().y() - self.height() // 2)

        # Spinner animation tick. The Windows 11 progress ring sweeps a
        # single arc smoothly so we drive it at ~60 Hz.
        self._spin = QTimer(self)
        self._spin.setInterval(16)
        self._spin.timeout.connect(self._tick)

        # Hard timeout — close even if no camera ever reports ready.
        self._max_timer = QTimer(self)
        self._max_timer.setSingleShot(True)
        self._max_timer.setInterval(self.MAX_LIFETIME_MS)
        self._max_timer.timeout.connect(self._begin_fade_out)

        # Minimum on-screen time so the splash doesn't blink in/out on a
        # cold start where every camera connects within ~50 ms.
        self._min_elapsed = False
        self._min_timer = QTimer(self)
        self._min_timer.setSingleShot(True)
        self._min_timer.setInterval(self.MIN_LIFETIME_MS)
        self._min_timer.timeout.connect(self._on_min_elapsed)

        # Fade in/out using window opacity.
        self._opacity = 0.0
        self.setWindowOpacity(0.0)
        self._fade_in = QPropertyAnimation(self, b"_opacity_prop", self)
        self._fade_in.setDuration(220)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)

        self._fade_out = QPropertyAnimation(self, b"_opacity_prop", self)
        self._fade_out.setDuration(260)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self._on_fade_out_done)

    # -- Qt property bridge so QPropertyAnimation can drive opacity --

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = float(value)
        self.setWindowOpacity(self._opacity)

    _opacity_prop = pyqtProperty(float, fget=_get_opacity, fset=_set_opacity)

    # -- public API --

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._spin.start()
        self._max_timer.start()
        self._min_timer.start()
        self._fade_in.start()

    def set_message(self, text: str) -> None:
        self._message = text
        self.update()

    def set_stage(self, text: str) -> None:
        """Update the current high-level stage (e.g. 'ONVIF aranıyor')."""
        self._stage = text
        self.update()

    def mark_camera_ready(self, camera_id: str) -> None:
        """Report that one camera has delivered its first frame."""
        if not camera_id:
            return
        self._ready_ids.add(camera_id)
        self._stage = "Kameralar bağlanıyor"
        self.set_message(self._format_progress())
        if self._total and len(self._ready_ids) >= self._total and self._min_elapsed:
            self._begin_fade_out()

    # -- internals --

    def _format_progress(self) -> str:
        if not self._total:
            return "Hazırlanıyor..."
        return f"{len(self._ready_ids)} / {self._total} kamera hazır"

    def _on_min_elapsed(self) -> None:
        self._min_elapsed = True
        # No cameras configured? Nothing to wait for — dismiss right away.
        if self._total == 0:
            self._begin_fade_out()
            return
        if len(self._ready_ids) >= self._total:
            self._begin_fade_out()

    def _tick(self) -> None:
        # ~360°/second — feels active but not jittery.
        self._angle = (self._angle + 6.0) % 360.0
        self.update()

    def _begin_fade_out(self) -> None:
        if not self._spin.isActive():
            return
        self._spin.stop()
        self._max_timer.stop()
        self._fade_out.start()

    def _on_fade_out_done(self) -> None:
        self.hide()
        self.finished.emit()

    # -- painting --

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Inner card rect (the visible window) leaves SHADOW_MARGIN on each
        # side for the painted drop shadow.
        rect = QRectF(SHADOW_MARGIN, SHADOW_MARGIN, CARD_W, CARD_H)
        radius = 24.0

        # Soft drop shadow — drawn manually so we never depend on
        # QGraphicsDropShadowEffect, which on Windows triggers
        # "UpdateLayeredWindowIndirect failed" with translucent windows.
        self._draw_shadow(painter, rect, radius)

        # Card background — gradient from elevated to slightly bluer.
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#26262a"))
        gradient.setColorAt(1.0, QColor("#1a1c22"))
        painter.fillPath(path, gradient)

        # Subtle inner border.
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Windows 11-style progress ring centred near the top of the card.
        cx = rect.center().x()
        cy = rect.top() + 80
        ring_r = 22.0
        self._draw_progress_ring(painter, QPointF(cx, cy), ring_r)

        # Title.
        painter.setPen(QColor("#f2f2f7"))
        title_font = QFont(painter.font())
        title_font.setPointSize(18)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.drawText(
            QRectF(rect.left(), cy + 36, rect.width(), 32),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "Tapo Viewer",
        )

        # Stage label (e.g. "ONVIF aranıyor"). Single line, keeps the user
        # informed about what the splash is currently doing.
        painter.setPen(QColor("#c7c7cc"))
        stage_font = QFont(painter.font())
        stage_font.setPointSize(12)
        stage_font.setWeight(QFont.Weight.Medium)
        painter.setFont(stage_font)
        painter.drawText(
            QRectF(rect.left(), cy + 70, rect.width(), 22),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._stage,
        )

        # Progress / status text underneath.
        painter.setPen(QColor("#9a9aa0"))
        sub_font = QFont(painter.font())
        sub_font.setPointSize(10)
        sub_font.setWeight(QFont.Weight.Normal)
        painter.setFont(sub_font)
        painter.drawText(
            QRectF(rect.left(), cy + 94, rect.width(), 22),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._message,
        )

    def _draw_shadow(self, painter: QPainter, rect: QRectF,
                      radius: float) -> None:
        """Paint a soft drop shadow under ``rect`` using a few stacked
        outlines. Cheap, dependency-free, and fits inside the widget."""
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i, alpha in enumerate((10, 18, 32, 60)):
            spread = (4 - i) * 3 + 2
            shadow_rect = rect.adjusted(-spread, -spread + 4,
                                         spread, spread + 4)
            painter.setPen(QPen(QColor(0, 0, 0, alpha), spread * 2))
            painter.drawRoundedRect(shadow_rect, radius + spread,
                                     radius + spread)
        painter.restore()

    def _draw_progress_ring(self, painter: QPainter, center: QPointF,
                             radius: float) -> None:
        """Windows 11 progress ring: a faint full track with a single
        accent-coloured arc sweeping around it."""
        track_rect = QRectF(center.x() - radius, center.y() - radius,
                             radius * 2, radius * 2)
        track_pen = QPen(QColor(255, 255, 255, 32))
        track_pen.setWidthF(3.5)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(track_rect)

        # Sweep arc: 110° wide, accent colour, rotating.
        arc_pen = QPen(QColor("#0a84ff"))
        arc_pen.setWidthF(3.5)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        # Qt arcs use 1/16 degree units; angles increase counter-clockwise
        # so we negate to spin clockwise like the Win11 ring.
        start_angle = int((-self._angle) * 16)
        span_angle = int(-110 * 16)
        painter.drawArc(track_rect, start_angle, span_angle)

        # A small leading dot at the head of the arc adds the trademark
        # Win11 highlight.
        head_phase = math.radians(-self._angle)
        head = QPointF(center.x() + radius * math.cos(head_phase),
                        center.y() + radius * math.sin(head_phase))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0a84ff"))
        painter.drawEllipse(head, 2.6, 2.6)
