"""Main application window: collapsible sidebar + camera grid."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .camera_grid import CameraGrid
from .camera_list import CameraList
from .config import AppConfig, Camera, load_config, save_config
from .dialogs import CameraDialog, SettingsDialog
from .ptz_panel import PtzPanel
from .resource_monitor import ResourceMonitor


SIDEBAR_WIDTH = 280
SIDEBAR_COLLAPSED_WIDTH = 48


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Tapo Viewer")
        self.resize(1280, 800)
        self.setMinimumSize(QSize(720, 600))

        self._config: AppConfig = load_config()
        self._collapsed: bool = bool(self._config.settings.sidebar_collapsed)

        # ---- Sidebar shell ----
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(
            SIDEBAR_COLLAPSED_WIDTH if self._collapsed else SIDEBAR_WIDTH
        )

        # Header row: title + toggle button.
        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("ToggleButton")
        self.toggle_btn.setFixedSize(36, 36)
        self.toggle_btn.setToolTip("Kenar çubuğunu daralt/genişlet")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle_sidebar)

        self.title_label = QLabel("Tapo Viewer")
        self.title_label.setObjectName("TitleLabel")

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        header_row.addWidget(self.toggle_btn)
        header_row.addWidget(self.title_label, 1)

        # Body widgets (hidden when collapsed).
        self.cameras_label = QLabel("Kameralar")
        self.cameras_label.setObjectName("SectionLabel")

        self.list_widget = CameraList()
        self.list_widget.selection_changed.connect(self._on_list_selection)
        self.list_widget.item_double_clicked_id.connect(self._on_list_double_clicked)
        self.list_widget.customContextMenuRequested.connect(self._on_list_context_menu)
        self.list_widget.order_changed.connect(self._on_order_changed)
        self.list_widget.mute_toggled.connect(self._on_mute_toggled)

        self.add_btn = QPushButton("+ Kamera Ekle")
        self.add_btn.setObjectName("PrimaryButton")
        self.add_btn.clicked.connect(self._on_add_camera)

        self.restore_btn = QPushButton("Tüm Izgara")
        self.restore_btn.clicked.connect(self._on_restore)
        self.restore_btn.setEnabled(False)

        self.settings_btn = QPushButton("Ayarlar")
        self.settings_btn.clicked.connect(self._on_open_settings)

        # PTZ panel.
        self.ptz_panel = PtzPanel()

        # Layout.
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 12)
        sidebar_layout.setSpacing(8)
        sidebar_layout.addLayout(header_row)

        # Wrap the body so we can hide/show it as a single unit.
        self.body_widget = QWidget()
        body_layout = QVBoxLayout(self.body_widget)
        body_layout.setContentsMargins(8, 6, 8, 0)
        body_layout.setSpacing(8)
        body_layout.addWidget(self.cameras_label)
        body_layout.addWidget(self.list_widget, 1)
        body_layout.addWidget(self.add_btn)
        body_layout.addWidget(self.restore_btn)
        body_layout.addSpacing(4)
        body_layout.addWidget(self.ptz_panel)
        body_layout.addStretch(0)
        body_layout.addWidget(self.settings_btn)

        sidebar_layout.addWidget(self.body_widget, 1)

        # ---- Grid ----
        self.grid = CameraGrid(settings=self._config.settings)
        self.grid.selection_changed.connect(self._on_grid_selection_changed)
        self.grid.tile_selected.connect(self._on_tile_selected)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.grid, 1)
        self.setCentralWidget(central)

        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Hazır")
        status.addWidget(self._status_label)
        self._resource_monitor = ResourceMonitor()
        status.addPermanentWidget(self._resource_monitor)

        # Shortcuts.
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._on_escape)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._on_add_camera)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self._on_open_settings)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._toggle_sidebar)

        self._refresh_camera_list()
        self.grid.set_cameras(self._config.cameras)
        self._apply_collapsed_state()
        self._update_status()
        self.ptz_panel.set_camera(None)

    # -- helpers --

    def _refresh_camera_list(self, selected_id: str | None = None) -> None:
        if selected_id is None:
            selected_id = self.list_widget.selected_camera_id()
        self.list_widget.populate(self._config.cameras, selected_id=selected_id)

    def _camera_by_id(self, cam_id: str | None) -> Camera | None:
        if not cam_id:
            return None
        return next((c for c in self._config.cameras if c.id == cam_id), None)

    def _selected_camera(self) -> Camera | None:
        return self._camera_by_id(self.list_widget.selected_camera_id())

    def _save(self) -> None:
        save_config(self._config)

    def _update_status(self) -> None:
        n = len(self._config.cameras)
        cols = self._config.settings.grid_columns
        rows = max(1, (n + cols - 1) // cols) if n else 1
        self._status_label.setText(
            f"{n} kamera   ·   {cols}×{rows} ızgara   ·   {self._config.settings.target_fps} FPS"
        )

    def _apply_collapsed_state(self) -> None:
        self.sidebar.setFixedWidth(
            SIDEBAR_COLLAPSED_WIDTH if self._collapsed else SIDEBAR_WIDTH
        )
        self.body_widget.setVisible(not self._collapsed)
        self.title_label.setVisible(not self._collapsed)
        # Bold, large arrows so the toggle is unmistakable when collapsed.
        self.toggle_btn.setText("›" if self._collapsed else "‹")
        self.toggle_btn.setToolTip(
            "Kenar çubuğunu genişlet" if self._collapsed else "Kenar çubuğunu daralt"
        )

    def _toggle_sidebar(self) -> None:
        self._collapsed = not self._collapsed
        self._config.settings.sidebar_collapsed = self._collapsed
        self._save()
        self._apply_collapsed_state()

    # -- handlers --

    def _on_list_selection(self, camera_id: str) -> None:
        cam = self._camera_by_id(camera_id) if camera_id else None
        self.ptz_panel.set_camera(cam)
        self.grid.select(camera_id or "")

    def _on_list_double_clicked(self, cam_id: str) -> None:
        if cam_id:
            self.grid.maximize(cam_id)

    def _on_list_context_menu(self, pos: QPoint) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        self.list_widget.setCurrentItem(item)

        menu = QMenu(self)
        edit_act = QAction("Düzenle", self)
        edit_act.triggered.connect(self._on_edit_camera)
        remove_act = QAction("Kaldır", self)
        remove_act.triggered.connect(self._on_remove_camera)
        menu.addAction(edit_act)
        menu.addSeparator()
        menu.addAction(remove_act)
        menu.exec(self.list_widget.viewport().mapToGlobal(pos))

    def _on_order_changed(self, ordered_ids: list) -> None:
        by_id = {c.id: c for c in self._config.cameras}
        new_order = [by_id[i] for i in ordered_ids if i in by_id]
        # Append anything missing (shouldn't happen, but stay safe).
        for c in self._config.cameras:
            if c.id not in ordered_ids:
                new_order.append(c)
        self._config.cameras = new_order
        self._save()
        self.grid.set_cameras(self._config.cameras)
        self._update_status()

    def _on_mute_toggled(self, camera_id: str, audio_enabled: bool) -> None:
        for cam in self._config.cameras:
            if cam.id == camera_id:
                cam.audio_enabled = audio_enabled
                break
        self._save()
        self.grid.set_cameras(self._config.cameras)

    def _on_tile_selected(self, camera_id: str) -> None:
        if not camera_id:
            return
        if self.list_widget.selected_camera_id() != camera_id:
            self.list_widget.select_by_id(camera_id)
        else:
            # Selection already correct, but make sure PTZ panel is up to date.
            self.ptz_panel.set_camera(self._camera_by_id(camera_id))

    def _on_add_camera(self) -> None:
        dlg = CameraDialog(parent=self)
        if dlg.exec() == CameraDialog.DialogCode.Accepted:
            cam = dlg.result_camera()
            if not cam.host and not cam.use_custom_url:
                QMessageBox.warning(self, "Eksik Bilgi", "Host/IP veya özel URL girilmelidir.")
                return
            self._config.cameras.append(cam)
            self._save()
            self._refresh_camera_list(selected_id=cam.id)
            self.grid.set_cameras(self._config.cameras)
            self._update_status()

    def _on_edit_camera(self) -> None:
        cam = self._selected_camera()
        if cam is None:
            return
        dlg = CameraDialog(parent=self, camera=cam)
        if dlg.exec() == CameraDialog.DialogCode.Accepted:
            updated = dlg.result_camera()
            for i, c in enumerate(self._config.cameras):
                if c.id == updated.id:
                    self._config.cameras[i] = updated
                    break
            self._save()
            self._refresh_camera_list(selected_id=updated.id)
            self.grid.set_cameras(self._config.cameras)
            self.ptz_panel.set_camera(self._camera_by_id(updated.id))

    def _on_remove_camera(self) -> None:
        cam = self._selected_camera()
        if cam is None:
            return
        confirm = QMessageBox.question(
            self,
            "Kamerayı Kaldır",
            f"\"{cam.name}\" kamerasını kaldırmak istediğinize emin misiniz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._config.cameras = [c for c in self._config.cameras if c.id != cam.id]
        self._save()
        self._refresh_camera_list()
        self.grid.set_cameras(self._config.cameras)
        self.ptz_panel.set_camera(self._selected_camera())
        self._update_status()

    def _on_open_settings(self) -> None:
        dlg = SettingsDialog(self, self._config.settings)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            new_settings = dlg.result_settings()
            # Preserve sidebar state across settings changes.
            new_settings.sidebar_collapsed = self._config.settings.sidebar_collapsed
            self._config.settings = new_settings
            self._save()
            # FPS / overlay / columns all apply live without restarting workers.
            self.grid.apply_settings(new_settings)
            self._update_status()

    def _on_grid_selection_changed(self, camera_id: str) -> None:
        self.restore_btn.setEnabled(bool(camera_id))

    def _on_restore(self) -> None:
        self.grid.restore()

    def _on_escape(self) -> None:
        if self.grid.is_maximized():
            self.grid.restore()

    # -- close --

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.ptz_panel.shutdown()
        self.grid.stop_all()
        self._resource_monitor.shutdown()
        self._save()
        super().closeEvent(event)
