"""Main application window: sidebar + camera grid."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .camera_grid import CameraGrid
from .config import AppConfig, Camera, load_config, save_config
from .dialogs import CameraDialog, SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Tapo Viewer")
        self.resize(1280, 800)
        self.setMinimumSize(QSize(960, 600))

        self._config: AppConfig = load_config()

        # ---- Sidebar ----
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(280)

        title = QLabel("Tapo Viewer")
        title.setObjectName("TitleLabel")

        cameras_label = QLabel("Kameralar")
        cameras_label.setObjectName("SectionLabel")

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_list_selection)
        self.list_widget.itemDoubleClicked.connect(self._on_list_double_clicked)

        add_btn = QPushButton("+ Kamera Ekle")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._on_add_camera)

        edit_btn = QPushButton("Düzenle")
        edit_btn.clicked.connect(self._on_edit_camera)
        self.edit_btn = edit_btn

        remove_btn = QPushButton("Kaldır")
        remove_btn.setObjectName("DangerButton")
        remove_btn.clicked.connect(self._on_remove_camera)
        self.remove_btn = remove_btn

        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)
        edit_row.addWidget(edit_btn)
        edit_row.addWidget(remove_btn)

        view_label = QLabel("Görünüm")
        view_label.setObjectName("SectionLabel")

        grid_row = QHBoxLayout()
        grid_row.setSpacing(8)
        grid_row.addWidget(QLabel("Sütun"))
        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(1, 8)
        self.grid_spin.setValue(self._config.settings.grid_columns)
        self.grid_spin.valueChanged.connect(self._on_grid_columns_changed)
        grid_row.addWidget(self.grid_spin, 1)

        self.restore_btn = QPushButton("Tüm Izgara")
        self.restore_btn.clicked.connect(self._on_restore)
        self.restore_btn.setEnabled(False)

        settings_btn = QPushButton("Ayarlar")
        settings_btn.clicked.connect(self._on_open_settings)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 18, 16, 16)
        sidebar_layout.setSpacing(8)
        sidebar_layout.addWidget(title)
        sidebar_layout.addSpacing(8)
        sidebar_layout.addWidget(cameras_label)
        sidebar_layout.addWidget(self.list_widget, 1)
        sidebar_layout.addWidget(add_btn)
        sidebar_layout.addLayout(edit_row)
        sidebar_layout.addSpacing(6)
        sidebar_layout.addWidget(view_label)
        sidebar_layout.addLayout(grid_row)
        sidebar_layout.addWidget(self.restore_btn)
        sidebar_layout.addSpacing(6)
        sidebar_layout.addWidget(settings_btn)

        # ---- Grid ----
        self.grid = CameraGrid(settings=self._config.settings)
        self.grid.selection_changed.connect(self._on_grid_selection_changed)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(self.grid, 1)
        self.setCentralWidget(central)

        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Hazır")
        status.addWidget(self._status_label)

        # Shortcuts
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._on_escape)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._on_add_camera)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self._on_open_settings)

        self._refresh_camera_list()
        self.grid.set_cameras(self._config.cameras)
        self._update_button_states()
        self._update_status()

    # -- helpers --

    def _refresh_camera_list(self) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for cam in self._config.cameras:
            item = QListWidgetItem(cam.name or cam.host)
            item.setData(Qt.ItemDataRole.UserRole, cam.id)
            item.setToolTip(cam.rtsp_url)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

    def _selected_camera(self) -> Camera | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        cam_id = item.data(Qt.ItemDataRole.UserRole)
        return next((c for c in self._config.cameras if c.id == cam_id), None)

    def _save(self) -> None:
        save_config(self._config)

    def _update_button_states(self) -> None:
        has_selection = self._selected_camera() is not None
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _update_status(self) -> None:
        n = len(self._config.cameras)
        self._status_label.setText(
            f"{n} kamera   ·   {self._config.settings.grid_columns} sütun   ·   {self._config.settings.target_fps} FPS"
        )

    # -- handlers --

    def _on_list_selection(self) -> None:
        self._update_button_states()

    def _on_list_double_clicked(self, item: QListWidgetItem) -> None:
        cam_id = item.data(Qt.ItemDataRole.UserRole)
        if cam_id:
            self.grid.maximize(cam_id)

    def _on_add_camera(self) -> None:
        dlg = CameraDialog(parent=self)
        if dlg.exec() == CameraDialog.DialogCode.Accepted:
            cam = dlg.result_camera()
            if not cam.host and not cam.use_custom_url:
                QMessageBox.warning(self, "Eksik Bilgi", "Host/IP veya özel URL girilmelidir.")
                return
            self._config.cameras.append(cam)
            self._save()
            self._refresh_camera_list()
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
            self._refresh_camera_list()
            self.grid.set_cameras(self._config.cameras)

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
        self._update_status()

    def _on_grid_columns_changed(self, value: int) -> None:
        self._config.settings.grid_columns = value
        self._save()
        self.grid.apply_settings(self._config.settings)
        self._update_status()

    def _on_open_settings(self) -> None:
        dlg = SettingsDialog(self, self._config.settings)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            new_settings = dlg.result_settings()
            target_fps_changed = new_settings.target_fps != self._config.settings.target_fps
            self._config.settings = new_settings
            self.grid_spin.blockSignals(True)
            self.grid_spin.setValue(new_settings.grid_columns)
            self.grid_spin.blockSignals(False)
            self._save()
            self.grid.apply_settings(new_settings)
            if target_fps_changed:
                # FPS change requires restarting workers.
                self.grid.stop_all()
                self.grid.set_cameras(self._config.cameras)
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
        self.grid.stop_all()
        self._save()
        super().closeEvent(event)
