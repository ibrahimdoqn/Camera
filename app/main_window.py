"""Main application window: collapsible sidebar + camera grid."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .camera_grid import CameraGrid
from .config import AppConfig, Camera, load_config, save_config
from .dialogs import CameraDialog, SettingsDialog
from .ptz_panel import PtzPanel


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
        self.toggle_btn = QPushButton("☰")
        self.toggle_btn.setObjectName("IconButton")
        self.toggle_btn.setFixedSize(32, 32)
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

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_list_selection)
        self.list_widget.itemDoubleClicked.connect(self._on_list_double_clicked)

        self.add_btn = QPushButton("+ Kamera Ekle")
        self.add_btn.setObjectName("PrimaryButton")
        self.add_btn.clicked.connect(self._on_add_camera)

        self.edit_btn = QPushButton("Düzenle")
        self.edit_btn.clicked.connect(self._on_edit_camera)

        self.remove_btn = QPushButton("Kaldır")
        self.remove_btn.setObjectName("DangerButton")
        self.remove_btn.clicked.connect(self._on_remove_camera)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)
        edit_row.addWidget(self.edit_btn)
        edit_row.addWidget(self.remove_btn)

        self.view_label = QLabel("Görünüm")
        self.view_label.setObjectName("SectionLabel")

        # Grid presets (1x1, 2x2, 3x3, 4x4).
        self._preset_buttons: dict[int, QPushButton] = {}
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        for n in (1, 2, 3, 4):
            btn = QPushButton(f"{n}×{n}")
            btn.setObjectName("PresetButton")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _checked=False, val=n: self._on_preset_clicked(val))
            self._preset_buttons[n] = btn
            preset_row.addWidget(btn)

        # Custom column count (for non-NxN layouts).
        col_row = QHBoxLayout()
        col_row.setSpacing(8)
        self.col_label = QLabel("Sütun")
        col_row.addWidget(self.col_label)
        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(1, 8)
        self.grid_spin.setValue(self._config.settings.grid_columns)
        self.grid_spin.valueChanged.connect(self._on_grid_columns_changed)
        col_row.addWidget(self.grid_spin, 1)

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
        body_layout.addLayout(edit_row)
        body_layout.addSpacing(4)
        body_layout.addWidget(self.view_label)
        body_layout.addLayout(preset_row)
        body_layout.addLayout(col_row)
        body_layout.addWidget(self.restore_btn)
        body_layout.addSpacing(4)
        body_layout.addWidget(self._make_separator())
        body_layout.addWidget(self.ptz_panel)
        body_layout.addStretch(0)
        body_layout.addWidget(self.settings_btn)

        sidebar_layout.addWidget(self.body_widget, 1)

        # ---- Grid ----
        self.grid = CameraGrid(settings=self._config.settings)
        self.grid.selection_changed.connect(self._on_grid_selection_changed)

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

        # Shortcuts
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._on_escape)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._on_add_camera)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self._on_open_settings)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._toggle_sidebar)

        self._refresh_camera_list()
        self.grid.set_cameras(self._config.cameras)
        self._update_button_states()
        self._update_preset_states()
        self._apply_collapsed_state()
        self._update_status()

    # -- helpers --

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setObjectName("Separator")
        sep.setFixedHeight(1)
        return sep

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

    def _update_preset_states(self) -> None:
        cols = self._config.settings.grid_columns
        for n, btn in self._preset_buttons.items():
            btn.setChecked(n == cols)

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
        self.toggle_btn.setText("›" if self._collapsed else "☰")
        self.toggle_btn.setToolTip(
            "Kenar çubuğunu genişlet" if self._collapsed else "Kenar çubuğunu daralt"
        )

    def _toggle_sidebar(self) -> None:
        self._collapsed = not self._collapsed
        self._config.settings.sidebar_collapsed = self._collapsed
        self._save()
        self._apply_collapsed_state()

    # -- handlers --

    def _on_list_selection(self) -> None:
        self._update_button_states()
        self.ptz_panel.set_camera(self._selected_camera())

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
            # Refresh PTZ binding if the edited camera is the selected one.
            if self._selected_camera() and self._selected_camera().id == updated.id:
                self.ptz_panel.set_camera(self._selected_camera())

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

    def _on_grid_columns_changed(self, value: int) -> None:
        self._config.settings.grid_columns = value
        self._save()
        self.grid.apply_settings(self._config.settings)
        self._update_preset_states()
        self._update_status()

    def _on_preset_clicked(self, n: int) -> None:
        if self._config.settings.grid_columns == n:
            # Re-check the active button so the user gets visible feedback.
            self._update_preset_states()
            return
        self.grid_spin.blockSignals(True)
        self.grid_spin.setValue(n)
        self.grid_spin.blockSignals(False)
        self._config.settings.grid_columns = n
        self._save()
        self.grid.apply_settings(self._config.settings)
        self._update_preset_states()
        self._update_status()

    def _on_open_settings(self) -> None:
        dlg = SettingsDialog(self, self._config.settings)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            new_settings = dlg.result_settings()
            target_fps_changed = new_settings.target_fps != self._config.settings.target_fps
            # Preserve sidebar state across settings changes.
            new_settings.sidebar_collapsed = self._config.settings.sidebar_collapsed
            self._config.settings = new_settings
            self.grid_spin.blockSignals(True)
            self.grid_spin.setValue(new_settings.grid_columns)
            self.grid_spin.blockSignals(False)
            self._save()
            self.grid.apply_settings(new_settings)
            if target_fps_changed:
                self.grid.stop_all()
                self.grid.set_cameras(self._config.cameras)
            self._update_preset_states()
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
        self._save()
        super().closeEvent(event)
