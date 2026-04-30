"""Animated startup splash screen.

A frameless, rounded, centred widget with a soft fade-in/fade-out and an
orbiting-dots spinner. The splash is responsible for keeping itself on
screen long enough for cameras to connect: callers can either tell it
how many cameras to wait for and report when each one delivers its first
frame (:meth:`mark_camera_ready`) or simply let the timeout expire.
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
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QWidget


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
        self.setFixedSize(440, 260)

        self._total = max(0, total_cameras)
        self._ready_ids: set[str] = set()
        self._message = "Yükleniyor..."
        self._angle = 0.0

        # Centre on the primary screen.
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.center().y() - self.height() // 2)

        # Spinner animation tick.
        self._spin = QTimer(self)
        self._spin.setInterval(33)  # ~30 Hz
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

        # Drop shadow.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

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

    def mark_camera_ready(self, camera_id: str) -> None:
        """Report that one camera has delivered its first frame."""
        if not camera_id:
            return
        self._ready_ids.add(camera_id)
        self.set_message(self._format_progress())
        if self._total and len(self._ready_ids) >= self._total and self._min_elapsed:
            self._begin_fade_out()

    # -- internals --

    def _format_progress(self) -> str:
        if not self._total:
            return "Yükleniyor..."
        return f"Kameralar bağlanıyor   {len(self._ready_ids)}/{self._total}"

    def _on_min_elapsed(self) -> None:
        self._min_elapsed = True
        # No cameras configured? Nothing to wait for — dismiss right away.
        if self._total == 0:
            self._begin_fade_out()
            return
        if len(self._ready_ids) >= self._total:
            self._begin_fade_out()

    def _tick(self) -> None:
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

        rect = QRectF(0, 0, self.width(), self.height()).adjusted(8, 8, -8, -8)
        radius = 24

        # Card background — gradient from elevated to slightly bluer.
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#26262a"))
        gradient.setColorAt(1.0, QColor("#1a1c22"))
        painter.fillPath(path, gradient)

        # Subtle inner border.
        painter.setPen(QPen(QColor(255, 255, 255, 25), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Spinner: 8 dots orbiting in the upper portion.
        cx = rect.center().x()
        cy = rect.top() + 84
        ring_r = 26.0
        dot_r = 4.5
        for i in range(8):
            phase = (self._angle + i * 45.0) * math.pi / 180.0
            x = cx + ring_r * math.cos(phase)
            y = cy + ring_r * math.sin(phase)
            alpha = 60 + int(195 * (i / 7.0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(10, 132, 255, alpha))
            painter.drawEllipse(QPointF(x, y), dot_r, dot_r)

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

        # Status / progress text.
        painter.setPen(QColor("#9a9aa0"))
        sub_font = QFont(painter.font())
        sub_font.setPointSize(11)
        sub_font.setWeight(QFont.Weight.Normal)
        painter.setFont(sub_font)
        painter.drawText(
            QRectF(rect.left(), cy + 72, rect.width(), 24),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._message,
        )
