"""Add/edit camera and settings dialogs."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import Camera, Settings


class CameraDialog(QDialog):
    """Add or edit a camera."""

    def __init__(self, parent: Optional[QWidget] = None, camera: Optional[Camera] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kamera Düzenle" if camera else "Kamera Ekle")
        self.setModal(True)
        self.setMinimumWidth(440)

        self._camera = camera

        title = QLabel("Kamera Bilgileri")
        title.setObjectName("TitleLabel")

        hint = QLabel(
            "Tapo kameralarda RTSP'yi etkinleştirmek için Tapo uygulamasında "
            "Kamera Hesabı oluşturmanız gerekir."
        )
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)

        self.name_edit = QLineEdit(camera.name if camera else "")
        self.name_edit.setPlaceholderText("Salon Kamerası")

        self.host_edit = QLineEdit(camera.host if camera else "")
        self.host_edit.setPlaceholderText("192.168.1.50")

        self.user_edit = QLineEdit(camera.username if camera else "")
        self.user_edit.setPlaceholderText("Tapo kamera kullanıcı adı")

        self.pass_edit = QLineEdit(camera.password if camera else "")
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Şifre")

        self.rtsp_port_spin = QSpinBox()
        self.rtsp_port_spin.setRange(1, 65535)
        self.rtsp_port_spin.setValue(camera.rtsp_port if camera else 554)

        self.onvif_port_spin = QSpinBox()
        self.onvif_port_spin.setRange(1, 65535)
        self.onvif_port_spin.setValue(camera.onvif_port if camera else 2020)

        self.stream_combo = QComboBox()
        self.stream_combo.addItem("HD (stream1)", "stream1")
        self.stream_combo.addItem("SD (stream2)", "stream2")
        if camera:
            idx = self.stream_combo.findData(camera.stream)
            if idx >= 0:
                self.stream_combo.setCurrentIndex(idx)

        self.custom_check = QCheckBox("Özel RTSP URL kullan")
        self.custom_check.setChecked(camera.use_custom_url if camera else False)
        self.custom_edit = QLineEdit(camera.custom_url if camera else "")
        self.custom_edit.setPlaceholderText("rtsp://kullanici:sifre@host:554/stream1")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Ad", self.name_edit)
        form.addRow("Host / IP", self.host_edit)
        form.addRow("Kullanıcı", self.user_edit)
        form.addRow("Şifre", self.pass_edit)
        form.addRow("RTSP portu", self.rtsp_port_spin)
        form.addRow("ONVIF portu", self.onvif_port_spin)
        form.addRow("Akış", self.stream_combo)
        form.addRow("", self.custom_check)
        form.addRow("Özel URL", self.custom_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setObjectName("PrimaryButton")
        save_btn.setText("Kaydet")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addWidget(buttons)

        self.custom_check.toggled.connect(self._update_custom_state)
        self._update_custom_state(self.custom_check.isChecked())

    def _update_custom_state(self, enabled: bool) -> None:
        self.custom_edit.setEnabled(enabled)
        self.host_edit.setEnabled(not enabled)
        self.rtsp_port_spin.setEnabled(not enabled)
        self.stream_combo.setEnabled(not enabled)

    def result_camera(self) -> Camera:
        name = self.name_edit.text().strip() or self.host_edit.text().strip() or "Kamera"
        if self._camera is None:
            return Camera.new(
                name=name,
                host=self.host_edit.text().strip(),
                username=self.user_edit.text(),
                password=self.pass_edit.text(),
                rtsp_port=self.rtsp_port_spin.value(),
                onvif_port=self.onvif_port_spin.value(),
                stream=self.stream_combo.currentData(),
                custom_url=self.custom_edit.text().strip(),
                use_custom_url=self.custom_check.isChecked(),
            )
        return Camera(
            id=self._camera.id,
            name=name,
            host=self.host_edit.text().strip(),
            username=self.user_edit.text(),
            password=self.pass_edit.text(),
            rtsp_port=self.rtsp_port_spin.value(),
            onvif_port=self.onvif_port_spin.value(),
            stream=self.stream_combo.currentData(),
            custom_url=self.custom_edit.text().strip(),
            use_custom_url=self.custom_check.isChecked(),
        )


class SettingsDialog(QDialog):
    """Application-wide preferences."""

    def __init__(self, parent: Optional[QWidget], settings: Settings) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ayarlar")
        self.setModal(True)
        self.setMinimumWidth(420)

        title = QLabel("Görüntüleme Ayarları")
        title.setObjectName("TitleLabel")

        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(1, 8)
        self.grid_spin.setValue(settings.grid_columns)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(settings.target_fps)

        self.reconnect_spin = QSpinBox()
        self.reconnect_spin.setRange(1, 60)
        self.reconnect_spin.setValue(int(settings.reconnect_delay))
        self.reconnect_spin.setSuffix(" sn")

        self.hw_combo = QComboBox()
        for opt in ("auto", "none", "dxva2", "d3d11va", "cuda"):
            self.hw_combo.addItem(opt)
        idx = self.hw_combo.findText(settings.hw_accel)
        if idx >= 0:
            self.hw_combo.setCurrentIndex(idx)

        self.overlay_check = QCheckBox("Kamera adı ve durum rozetini göster")
        self.overlay_check.setChecked(settings.show_overlay)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Sütun sayısı", self.grid_spin)
        form.addRow("Hedef FPS", self.fps_spin)
        form.addRow("Yeniden bağlanma", self.reconnect_spin)
        form.addRow("HW hızlandırma", self.hw_combo)
        form.addRow("", self.overlay_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setObjectName("PrimaryButton")
        save_btn.setText("Uygula")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("İptal")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addWidget(buttons)

    def result_settings(self) -> Settings:
        return Settings(
            grid_columns=self.grid_spin.value(),
            target_fps=self.fps_spin.value(),
            hw_accel=self.hw_combo.currentText(),
            reconnect_delay=float(self.reconnect_spin.value()),
            show_overlay=self.overlay_check.isChecked(),
        )
