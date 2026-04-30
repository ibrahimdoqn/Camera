"""Sidebar camera list with drag-and-drop reordering and per-row mute toggle."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import Camera


ROW_HEIGHT = 56


class CameraRow(QWidget):
    """A modern card-style row: status dot, name + host, and mute toggle.

    The row paints its own selection / hover background via QSS dynamic
    properties, so the underlying QListWidget items can stay unstyled.
    Mouse events on the empty parts of the row fall through to the list
    so selection and drag-and-drop continue to work.
    """

    mute_toggled = pyqtSignal(str, bool)  # camera_id, audio_enabled

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
        self._dot.setFixedSize(8, 8)
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
        self._mute_btn.setFixedSize(30, 30)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._on_mute_clicked)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_col, 1)
        layout.addWidget(self._mute_btn, 0, Qt.AlignmentFlag.AlignVCenter)

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

    # -- internals --

    def _apply_camera(self, camera: Camera) -> None:
        self._name.setText(camera.name or "Kamera")
        self._sub.setText(camera.host or "—")
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


class CameraList(QListWidget):
    """Drag-and-drop sortable list of camera rows."""

    order_changed = pyqtSignal(list)              # list[str] of camera ids
    mute_toggled = pyqtSignal(str, bool)
    selection_changed = pyqtSignal(str)           # current camera_id ("" if none)
    item_double_clicked_id = pyqtSignal(str)      # camera_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CameraList")
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.model().rowsMoved.connect(self._emit_order)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.itemDoubleClicked.connect(self._emit_double_click)

    def populate(self, cameras: list[Camera], selected_id: Optional[str] = None) -> None:
        self.blockSignals(True)
        self.clear()
        for cam in cameras:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cam.id)
            row = CameraRow(cam)
            row.setToolTip(cam.rtsp_url)
            row.mute_toggled.connect(self.mute_toggled)
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

    def _emit_order(self, *_args) -> None:
        self.order_changed.emit(self._ordered_ids())

    def _on_selection_changed(self) -> None:
        self._refresh_selection_state()
        self.selection_changed.emit(self.selected_camera_id() or "")

    def _emit_double_click(self, item: QListWidgetItem) -> None:
        cam_id = item.data(Qt.ItemDataRole.UserRole)
        if cam_id:
            self.item_double_clicked_id.emit(cam_id)
