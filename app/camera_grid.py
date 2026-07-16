"""Grid view of camera tiles.

Tiles are sized to preserve a fixed aspect ratio (16:9 by default), so the
grid never stretches a tile vertically. Both column and row counts are
honored: rows are computed from camera count and the chosen column count.

Click a tile to select it; double-click to maximize / restore.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import QStackedLayout, QWidget

from .camera_tile import CameraTile
from .config import Camera, Settings


class AspectGrid(QWidget):
    """Lays out children in a grid, keeping each cell at a fixed aspect ratio."""

    def __init__(self, parent: Optional[QWidget] = None, aspect: float = 16 / 9,
                 columns: int = 2, spacing: int = 12, margin: int = 12) -> None:
        super().__init__(parent)
        self._tiles: list[QWidget] = []
        self._aspect = aspect
        self._columns = max(1, columns)
        self._spacing = spacing
        self._margin = margin

    def set_tiles(self, tiles: list[QWidget]) -> None:
        # Detach previous children we still own.
        for t in self._tiles:
            if t not in tiles:
                t.setParent(None)
        self._tiles = list(tiles)
        for t in self._tiles:
            t.setParent(self)
            t.show()
        self._relayout()

    def set_columns(self, columns: int) -> None:
        cols = max(1, columns)
        if cols == self._columns:
            return
        self._columns = cols
        self._relayout()

    def set_aspect(self, aspect: float) -> None:
        self._aspect = max(0.1, aspect)
        self._relayout()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        n = len(self._tiles)
        if n == 0 or self.width() <= 0 or self.height() <= 0:
            return

        cols = min(self._columns, n)
        rows = (n + cols - 1) // cols

        avail_w = self.width() - 2 * self._margin
        avail_h = self.height() - 2 * self._margin
        if avail_w <= 0 or avail_h <= 0:
            return

        # Try to fit by width first.
        cell_w = (avail_w - (cols - 1) * self._spacing) / cols
        cell_h = cell_w / self._aspect

        # If that overflows vertically, fit by height instead.
        total_h = cell_h * rows + (rows - 1) * self._spacing
        if total_h > avail_h:
            cell_h = (avail_h - (rows - 1) * self._spacing) / rows
            cell_w = cell_h * self._aspect

        total_w = cell_w * cols + (cols - 1) * self._spacing
        total_h = cell_h * rows + (rows - 1) * self._spacing

        offset_x = (self.width() - total_w) / 2
        offset_y = (self.height() - total_h) / 2

        for i, tile in enumerate(self._tiles):
            r, c = divmod(i, cols)
            x = offset_x + c * (cell_w + self._spacing)
            y = offset_y + r * (cell_h + self._spacing)
            tile.setGeometry(int(x), int(y), int(cell_w), int(cell_h))


class CameraGrid(QWidget):
    """Holds CameraTile widgets in a grid; supports maximizing one tile."""

    selection_changed = pyqtSignal(str)  # emits when maximize toggles
    tile_selected = pyqtSignal(str)      # emits on tile single click
    tile_first_frame = pyqtSignal(str)   # emits once per tile when its first
                                         # frame is received (for splash)
    tile_status_changed = pyqtSignal(str, str)  # camera_id, status

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = settings
        # Insertion-ordered, drives display order.
        self._tiles: dict[str, CameraTile] = {}
        self._maximized_id: Optional[str] = None
        self._selected_id: Optional[str] = None

        self._stack = QStackedLayout(self)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackOne)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._grid_host = AspectGrid(columns=settings.grid_columns)
        self._max_host = AspectGrid(columns=1)

        self._stack.addWidget(self._grid_host)
        self._stack.addWidget(self._max_host)
        self._stack.setCurrentIndex(0)

    # -- public API --

    def set_cameras(self, cameras: list[Camera]) -> None:
        existing = set(self._tiles.keys())
        incoming = {c.id for c in cameras}

        for cam_id in existing - incoming:
            tile = self._tiles.pop(cam_id)
            tile.stop()
            tile.setParent(None)
            tile.deleteLater()

        # Rebuild ordered dict so display order matches the camera list.
        new_order: dict[str, CameraTile] = {}
        for cam in cameras:
            tile = self._tiles.get(cam.id)
            if tile is None:
                tile = CameraTile(
                    camera=cam,
                    target_fps=self._settings.target_fps,
                    reconnect_delay=self._settings.reconnect_delay,
                    show_overlay=self._settings.show_overlay,
                    hw_accel=self._settings.hw_accel,
                    playback_backend=self._settings.playback_backend,
                )
                tile.clicked.connect(self._on_tile_clicked)
                tile.double_clicked.connect(self._on_tile_double_clicked)
                tile.first_frame.connect(self.tile_first_frame)
                tile.status_changed.connect(self.tile_status_changed)
                tile.start()
            else:
                tile.update_camera(cam)
            new_order[cam.id] = tile
        self._tiles = new_order

        if self._maximized_id and self._maximized_id not in self._tiles:
            self._maximized_id = None
            self._stack.setCurrentIndex(0)
            self.selection_changed.emit("")
        if self._selected_id and self._selected_id not in self._tiles:
            self._selected_id = None

        self._refresh_layout()

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        for tile in self._tiles.values():
            tile.set_show_overlay(settings.show_overlay)
            tile.set_target_fps(settings.target_fps)
            # Switch the playback engine *before* the HW-accel mode: the
            # engine change may restart the tile, and doing hw_accel first
            # would waste that restart.
            tile.set_playback_backend(settings.playback_backend)
            tile.set_hw_accel(settings.hw_accel)
        self._grid_host.set_columns(settings.grid_columns)
        self._refresh_layout()

    def stop_all(self) -> None:
        for tile in self._tiles.values():
            tile.stop()

    def stop_all_and_wait(self) -> None:
        for tile in self._tiles.values():
            tile.stop_and_wait()

    def is_maximized(self) -> bool:
        return self._maximized_id is not None

    def maximize(self, camera_id: str) -> None:
        if camera_id not in self._tiles:
            return
        self._maximized_id = camera_id
        tile = self._tiles[camera_id]
        self._grid_host.set_tiles(
            [t for t in self._tiles.values() if t is not tile]
        )
        self._max_host.set_tiles([tile])
        self._stack.setCurrentIndex(1)
        self.selection_changed.emit(camera_id)

    def restore(self) -> None:
        if self._maximized_id is None:
            return
        self._maximized_id = None
        self._max_host.set_tiles([])
        self._stack.setCurrentIndex(0)
        self._refresh_layout()
        self.selection_changed.emit("")

    def toggle_maximize(self, camera_id: str) -> None:
        if self._maximized_id == camera_id:
            self.restore()
        else:
            self.maximize(camera_id)

    def select(self, camera_id: str) -> None:
        if self._selected_id == camera_id:
            return
        self._selected_id = camera_id
        for cid, tile in self._tiles.items():
            tile.set_selected(cid == camera_id)

    # -- internal --

    def _on_tile_clicked(self, camera_id: str) -> None:
        self.select(camera_id)
        self.tile_selected.emit(camera_id)

    def _on_tile_double_clicked(self, camera_id: str) -> None:
        self.select(camera_id)
        self.tile_selected.emit(camera_id)
        self.toggle_maximize(camera_id)

    def _refresh_layout(self) -> None:
        if self._maximized_id is None:
            self._grid_host.set_tiles(list(self._tiles.values()))
        else:
            tile = self._tiles.get(self._maximized_id)
            others = [t for t in self._tiles.values() if t is not tile]
            self._grid_host.set_tiles(others)
            if tile is not None:
                self._max_host.set_tiles([tile])

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._maximized_id is not None:
            self.restore()
            event.accept()
            return
        super().keyPressEvent(event)
