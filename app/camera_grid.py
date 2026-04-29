"""Grid view of camera tiles with click-to-maximize."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QStackedLayout, QWidget

from .camera_tile import CameraTile
from .config import Camera, Settings


class CameraGrid(QWidget):
    """Holds CameraTile widgets in a grid; supports maximizing one tile."""

    selection_changed = pyqtSignal(str)  # camera id or "" when not maximized

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._tiles: dict[str, CameraTile] = {}
        self._maximized_id: Optional[str] = None

        self._stack = QStackedLayout(self)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackOne)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._grid_host = QWidget(self)
        self._grid_layout = QGridLayout(self._grid_host)
        self._grid_layout.setContentsMargins(12, 12, 12, 12)
        self._grid_layout.setSpacing(12)

        self._max_host = QWidget(self)
        self._max_layout = QGridLayout(self._max_host)
        self._max_layout.setContentsMargins(12, 12, 12, 12)
        self._max_layout.setSpacing(0)

        self._stack.addWidget(self._grid_host)
        self._stack.addWidget(self._max_host)
        self._stack.setCurrentIndex(0)

    # -- public API --

    def set_cameras(self, cameras: list[Camera]) -> None:
        existing = set(self._tiles.keys())
        incoming = {c.id for c in cameras}

        # Remove tiles for cameras no longer present.
        for cam_id in existing - incoming:
            tile = self._tiles.pop(cam_id)
            tile.stop()
            tile.setParent(None)
            tile.deleteLater()

        # Add or update.
        for cam in cameras:
            tile = self._tiles.get(cam.id)
            if tile is None:
                tile = CameraTile(
                    camera=cam,
                    target_fps=self._settings.target_fps,
                    reconnect_delay=self._settings.reconnect_delay,
                    show_overlay=self._settings.show_overlay,
                )
                tile.clicked.connect(self._on_tile_clicked)
                tile.double_clicked.connect(self._on_tile_double_clicked)
                self._tiles[cam.id] = tile
                tile.start()
            else:
                tile.update_camera(cam)

        if self._maximized_id and self._maximized_id not in self._tiles:
            self._maximized_id = None
            self._stack.setCurrentIndex(0)
            self.selection_changed.emit("")

        self._relayout()

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        for tile in self._tiles.values():
            tile.set_show_overlay(settings.show_overlay)
        self._relayout()

    def stop_all(self) -> None:
        for tile in self._tiles.values():
            tile.stop()

    def is_maximized(self) -> bool:
        return self._maximized_id is not None

    def maximize(self, camera_id: str) -> None:
        if camera_id not in self._tiles:
            return
        self._maximized_id = camera_id
        # Detach all tiles from grid, attach selected one to max layout.
        self._clear_layout(self._max_layout)
        tile = self._tiles[camera_id]
        tile.setParent(self._max_host)
        self._max_layout.addWidget(tile, 0, 0)
        self._stack.setCurrentIndex(1)
        self.selection_changed.emit(camera_id)

    def restore(self) -> None:
        if self._maximized_id is None:
            return
        self._maximized_id = None
        self._stack.setCurrentIndex(0)
        self._relayout()
        self.selection_changed.emit("")

    def toggle_maximize(self, camera_id: str) -> None:
        if self._maximized_id == camera_id:
            self.restore()
        else:
            self.maximize(camera_id)

    # -- internal --

    def _on_tile_clicked(self, camera_id: str) -> None:
        self.toggle_maximize(camera_id)

    def _on_tile_double_clicked(self, camera_id: str) -> None:
        self.toggle_maximize(camera_id)

    def _clear_layout(self, layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _relayout(self) -> None:
        if self._maximized_id is not None:
            return
        self._clear_layout(self._grid_layout)
        cols = max(1, self._settings.grid_columns)
        tiles = list(self._tiles.values())
        if not tiles:
            return
        for idx, tile in enumerate(tiles):
            row, col = divmod(idx, cols)
            tile.setParent(self._grid_host)
            tile.show()
            self._grid_layout.addWidget(tile, row, col)
        # Keep columns evenly stretched.
        for c in range(cols):
            self._grid_layout.setColumnStretch(c, 1)
        rows = (len(tiles) + cols - 1) // cols
        for r in range(rows):
            self._grid_layout.setRowStretch(r, 1)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._maximized_id is not None:
            self.restore()
            event.accept()
            return
        super().keyPressEvent(event)
