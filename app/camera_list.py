"""Sidebar camera list with drag-and-drop reordering, mute toggle, and a
3-dot overflow menu (info / edit / remove).

The row paints its own rounded card, hover state and selection so the
underlying QListWidget items stay completely unstyled. That lets the
drag pixmap reuse the rendered card directly (rounded corners and all),
and gives the sidebar a tight, modern look without nested widgets.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import Camera


ROW_HEIGHT = 60


class CameraRow(QWidget):
    """A modern card-style row: status dot, camera name + status caption,
    mute toggle, and a 3-dot overflow menu.

    The row paints its own selection / hover background via QSS dynamic
    properties, so the underlying QListWidget items can stay unstyled.
    Mouse events on the empty parts of the row fall through to the list
    so selection and drag-and-drop continue to work.
    """

    mute_toggled = pyqtSignal(str, bool)            # camera_id, audio_enabled
    menu_requested = pyqtSignal(str, QPoint)        # camera_id, global pos

    def __init__(self, camera: Camera, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cam_id = camera.id
        self._selected = False
        self.setObjectName("CameraRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._dot = QLabel()
        self._dot.setObjectName("CameraDot")
        self._dot.setFixedSize(12, 12)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._name = QLabel()
        self._name.setObjectName("CameraRowName")
        self._name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._sub = QLabel()
        self._sub.setObjectName("CameraRowSub")
        self._sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._sub.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(self._name)
        text_col.addWidget(self._sub)

        self._mute_btn = QPushButton()
        self._mute_btn.setObjectName("MuteButton")
        self._mute_btn.setFixedSize(28, 28)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._on_mute_clicked)

        self._menu_btn = OverflowButton()
        self._menu_btn.setObjectName("OverflowButton")
        self._menu_btn.setFixedSize(28, 28)
        self._menu_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu_btn.setToolTip("Daha fazla")
        self._menu_btn.clicked.connect(self._on_menu_clicked)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_col, 1)
        layout.addWidget(self._mute_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._menu_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_camera(camera)

    def update_camera(self, camera: Camera) -> None:
        self._cam_id = camera.id
        self._apply_camera(camera)

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.setProperty("selected", selected)
        # Re-polish so the QSS [selected="true"] selector takes effect.
        self.style().unpolish(self)
        self.style().polish(self)

    def camera_id(self) -> str:
        return self._cam_id

    # -- rendering of a self-contained, rounded drag pixmap --

    def render_drag_pixmap(self) -> QPixmap:
        """Return a rounded, drop-shadowed copy of this row for use as a
        drag pixmap. ``QWidget.grab()`` ignores the QSS ``border-radius``
        because Qt always rasterises into a rectangular buffer, leaving an
        ugly square preview during drag."""
        dpr = self.devicePixelRatioF() or 1.0
        size = self.size()
        pix = QPixmap(int(size.width() * dpr), int(size.height() * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = 12.0
        rect = QRectF(0, 0, size.width(), size.height()).adjusted(0.5, 0.5, -0.5, -0.5)
        # Solid card background so the dragged item is opaque against the
        # cursor and reads cleanly even over busy video frames.
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        # Match the elevated background so the drag preview blends with the
        # sidebar style rather than introducing a foreign colour.
        painter.fillPath(path, QColor("#3a3a3c"))
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.drawPath(path)
        # Render the live row into the rounded canvas.
        painter.setClipPath(path)
        # render() picks up the styled QSS contents.
        self.render(painter, QPoint(0, 0))
        painter.end()
        return pix

    # -- internals --

    def _apply_camera(self, camera: Camera) -> None:
        self._name.setText(camera.name or "Kamera")
        # Modern lists never bury the IP up front. Show a soft caption that
        # describes the device class instead — the IP is one click away in
        # the overflow menu (Bilgi / Info).
        if camera.use_custom_url and camera.custom_url:
            self._sub.setText("Özel RTSP")
        elif camera.host:
            self._sub.setText("IP kamera")
        else:
            self._sub.setText("Yapılandırılmamış")
        self._set_mute_visual(camera.audio_enabled)

    def _set_mute_visual(self, audio_on: bool) -> None:
        self._mute_btn.blockSignals(True)
        self._mute_btn.setChecked(audio_on)
        self._mute_btn.setText("🔊" if audio_on else "🔇")
        self._mute_btn.setToolTip("Sesi kapat" if audio_on else "Sesi aç")
        self._mute_btn.blockSignals(False)

    def _on_mute_clicked(self) -> None:
        new_state = self._mute_btn.isChecked()
        self._set_mute_visual(new_state)
        self.mute_toggled.emit(self._cam_id, new_state)

    def _on_menu_clicked(self) -> None:
        # Open the menu just under the button so it visually anchors there.
        anchor = self._menu_btn.mapToGlobal(QPoint(0, self._menu_btn.height()))
        self.menu_requested.emit(self._cam_id, anchor)


class OverflowButton(QPushButton):
    """A 3-dot vertical "more" button. Painted instead of using a glyph so
    the dots are perfectly centred regardless of the underlying font."""

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        cx = rect.center().x() + 0.5
        cy = rect.center().y() + 0.5
        spacing = 5.0
        radius = 1.6
        color = QColor("#f2f2f7") if self.underMouse() else QColor("#c7c7cc")
        if not self.isEnabled():
            color = QColor("#6a6a70")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for dy in (-spacing, 0.0, spacing):
            painter.drawEllipse(QRectF(cx - radius, cy - radius + dy,
                                        radius * 2, radius * 2))


class CameraList(QListWidget):
    """Drag-and-drop sortable list of camera rows."""

    order_changed = pyqtSignal(list)              # list[str] of camera ids
    mute_toggled = pyqtSignal(str, bool)
    selection_changed = pyqtSignal(str)           # current camera_id ("" if none)
    item_double_clicked_id = pyqtSignal(str)      # camera_id
    overflow_menu_requested = pyqtSignal(str, QPoint)  # camera_id, global pos

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CameraList")
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.model().rowsMoved.connect(self._on_rows_moved)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.itemDoubleClicked.connect(self._emit_double_click)
        # Track post-drop animation refs so they aren't GC'd mid-flight.
        self._row_anims: list[QPropertyAnimation] = []

    def populate(self, cameras: list[Camera], selected_id: Optional[str] = None) -> None:
        # ``clear()`` deletes the existing CameraRow widgets, which in turn
        # destroys any QPropertyAnimation we parented to them. Drop the
        # stale Python proxies first so subsequent ``_animate_settle`` calls
        # don't poke at deleted C++ objects.
        self._row_anims.clear()
        self.blockSignals(True)
        self.clear()
        for cam in cameras:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cam.id)
            row = CameraRow(cam)
            row.mute_toggled.connect(self.mute_toggled)
            row.menu_requested.connect(self.overflow_menu_requested)
            item.setSizeHint(QSize(180, ROW_HEIGHT + 4))
            self.addItem(item)
            self.setItemWidget(item, row)
            if selected_id and cam.id == selected_id:
                self.setCurrentItem(item)
                row.set_selected(True)
        self.blockSignals(False)
        self._refresh_selection_state()

    def selected_camera_id(self) -> Optional[str]:
        item = self.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def select_by_id(self, camera_id: str) -> None:
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == camera_id:
                self.setCurrentItem(item)
                return

    # -- internals --

    def _refresh_selection_state(self) -> None:
        current = self.currentItem()
        for i in range(self.count()):
            item = self.item(i)
            row = self.itemWidget(item)
            if isinstance(row, CameraRow):
                row.set_selected(item is current)

    def _ordered_ids(self) -> list[str]:
        return [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]

    def _on_rows_moved(self, *_args) -> None:
        """Fire ``order_changed`` after the drag has fully unwound.

        Emitting synchronously from inside the model's own ``rowsMoved``
        callback leaves Qt's drag-and-drop machinery half-initialised, so
        the *next* drag locks the UI up. Deferring the emit (and the
        settle animation) to the next event-loop tick avoids the
        re-entrancy and lets every subsequent drag work cleanly."""
        ids = self._ordered_ids()
        QTimer.singleShot(0, lambda i=ids: self._finish_drop(i))

    def _finish_drop(self, ids: list[str]) -> None:
        self.order_changed.emit(ids)
        self._animate_settle()

    def _animate_settle(self) -> None:
        # Drop stale animation proxies; some may point at deleted C++
        # objects (their parent widget was destroyed by ``populate()``).
        live: list[QPropertyAnimation] = []
        for anim in self._row_anims:
            try:
                if anim.state() == QPropertyAnimation.State.Running:
                    live.append(anim)
            except RuntimeError:
                # underlying QObject already deleted — skip.
                continue
        self._row_anims = live
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            if widget is None:
                continue
            effect = widget.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(220)
            anim.setStartValue(0.55)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            self._row_anims.append(anim)

    def startDrag(self, supportedActions) -> None:  # noqa: N802
        """Use a rounded snapshot of the row as the drag pixmap so the
        camera visibly travels with the cursor (Apple-style) — and the
        preview matches the row's QSS rounded corners instead of the
        ``QWidget.grab()`` rectangle."""
        item = self.currentItem()
        if item is None:
            return super().startDrag(supportedActions)
        widget = self.itemWidget(item)
        if not isinstance(widget, CameraRow):
            return super().startDrag(supportedActions)
        try:
            indexes = [self.indexFromItem(item)]
            mime = self.model().mimeData(indexes)
        except Exception:
            return super().startDrag(supportedActions)
        if mime is None:
            return super().startDrag(supportedActions)
        pixmap = widget.render_drag_pixmap()
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec(supportedActions, Qt.DropAction.MoveAction)

    def _on_selection_changed(self) -> None:
        self._refresh_selection_state()
        self.selection_changed.emit(self.selected_camera_id() or "")

    def _emit_double_click(self, item: QListWidgetItem) -> None:
        cam_id = item.data(Qt.ItemDataRole.UserRole)
        if cam_id:
            self.item_double_clicked_id.emit(cam_id)
