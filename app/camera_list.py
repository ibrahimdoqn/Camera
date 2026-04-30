"""Sidebar camera list with drag-and-drop reordering and per-row mute toggle."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .config import Camera


class CameraRow(QWidget):
    """A row in the camera list: name + mute toggle button.

    The row's name label is mouse-transparent so clicks fall through to the
    parent QListWidget viewport, which handles selection and drag-and-drop.
    The mute button keeps its own click handling.
    """

    mute_toggled = pyqtSignal(str, bool)  # camera_id, audio_enabled

    def __init__(self, camera: Camera, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cam_id = camera.id

        self._name = QLabel(camera.name or camera.host)
        self._name.setObjectName("CameraRowName")
        self._name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._mute_btn = QPushButton()
        self._mute_btn.setObjectName("MuteButton")
        self._mute_btn.setFixedSize(28, 24)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._on_mute_clicked)
        self._set_mute_visual(camera.audio_enabled)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self._name, 1)
        layout.addWidget(self._mute_btn, 0)

    def update_camera(self, camera: Camera) -> None:
        self._cam_id = camera.id
        self._name.setText(camera.name or camera.host)
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
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformItemSizes(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model().rowsMoved.connect(self._emit_order)
        self.itemSelectionChanged.connect(self._emit_selection)
        self.itemDoubleClicked.connect(self._emit_double_click)

    def populate(self, cameras: list[Camera], selected_id: Optional[str] = None) -> None:
        self.blockSignals(True)
        self.clear()
        for cam in cameras:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cam.id)
            item.setToolTip(cam.rtsp_url)
            row = CameraRow(cam)
            row.mute_toggled.connect(self.mute_toggled)
            item.setSizeHint(row.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, row)
            if selected_id and cam.id == selected_id:
                self.setCurrentItem(item)
        self.blockSignals(False)

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

    def _ordered_ids(self) -> list[str]:
        return [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]

    def _emit_order(self, *_args) -> None:
        self.order_changed.emit(self._ordered_ids())

    def _emit_selection(self) -> None:
        self.selection_changed.emit(self.selected_camera_id() or "")

    def _emit_double_click(self, item: QListWidgetItem) -> None:
        cam_id = item.data(Qt.ItemDataRole.UserRole)
        if cam_id:
            self.item_double_clicked_id.emit(cam_id)
