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
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import Camera, Settings
from .stream_worker import detect_supported_hw_accels


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
        # Preserve fields the dialog does not edit. Without this, saving a
        # camera would silently clear ``audio_enabled``, ``visible``,
        # ``mac_address``, and ``last_seen_host`` because they fall back to
        # dataclass defaults — that would, for example, force MAC-based
        # rediscovery to start from scratch and re-show a user-hidden
        # camera.
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
            audio_enabled=self._camera.audio_enabled,
            visible=getattr(self._camera, "visible", True),
            mac_address=self._camera.mac_address,
            last_seen_host=self._camera.last_seen_host,
        )


class SettingsDialog(QDialog):
    """Application-wide preferences."""

    def __init__(self, parent: Optional[QWidget], settings: Settings) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ayarlar")
        self.setModal(True)
        self.setMinimumWidth(440)

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

        # Only expose hardware acceleration modes that the current platform
        # could plausibly run. Showing ``cuda`` on a non-NVIDIA GPU or
        # ``d3d11va`` on Linux just leaves users staring at black tiles,
        # because FFmpeg quietly falls through to a path that produces no
        # frames. ``auto`` and ``none`` are always present. If the user's
        # saved setting refers to a now-unavailable mode (e.g. they moved
        # config files between machines), we add it back so the dropdown
        # still reflects what's actually persisted instead of silently
        # rewriting it.
        self.hw_combo = QComboBox()
        supported = list(detect_supported_hw_accels())
        if settings.hw_accel and settings.hw_accel not in supported:
            supported.append(settings.hw_accel)
        for opt in supported:
            self.hw_combo.addItem(opt)
        idx = self.hw_combo.findText(settings.hw_accel)
        if idx >= 0:
            self.hw_combo.setCurrentIndex(idx)

        self.overlay_check = QCheckBox("Kamera adı ve durum rozetini göster")
        self.overlay_check.setChecked(settings.show_overlay)

        # Diagnostics section: file logging + IP rediscovery.
        self.logging_check = QCheckBox("Log kayıtlarını dosyaya yaz")
        self.logging_check.setToolTip(
            "Hata ayıklama için olayları %APPDATA%/TapoViewer/logs altına yazar."
        )
        self.logging_check.setChecked(bool(settings.logging_enabled))

        self.log_level_combo = QComboBox()
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            self.log_level_combo.addItem(level)
        idx = self.log_level_combo.findText(settings.log_level)
        if idx >= 0:
            self.log_level_combo.setCurrentIndex(idx)

        self.rediscover_check = QCheckBox(
            "IP değişirse MAC adresine göre yerel ağı tarayarak yeniden bul"
        )
        self.rediscover_check.setChecked(bool(settings.ip_rediscovery_enabled))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Sütun sayısı", self.grid_spin)
        form.addRow("Hedef FPS", self.fps_spin)
        form.addRow("Yeniden bağlanma", self.reconnect_spin)
        form.addRow("HW hızlandırma", self.hw_combo)
        form.addRow("", self.overlay_check)

        diag_title = QLabel("Tanılama")
        diag_title.setObjectName("SectionLabel")

        diag_form = QFormLayout()
        diag_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        diag_form.setHorizontalSpacing(14)
        diag_form.setVerticalSpacing(10)
        diag_form.addRow("", self.logging_check)
        diag_form.addRow("Log seviyesi", self.log_level_combo)
        diag_form.addRow("", self.rediscover_check)

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
        layout.addWidget(diag_title)
        layout.addLayout(diag_form)
        layout.addStretch(1)
        layout.addWidget(buttons)

        self.logging_check.toggled.connect(self.log_level_combo.setEnabled)
        self.log_level_combo.setEnabled(self.logging_check.isChecked())

    def result_settings(self) -> Settings:
        return Settings(
            grid_columns=self.grid_spin.value(),
            target_fps=self.fps_spin.value(),
            hw_accel=self.hw_combo.currentText(),
            reconnect_delay=float(self.reconnect_spin.value()),
            show_overlay=self.overlay_check.isChecked(),
            logging_enabled=self.logging_check.isChecked(),
            log_level=self.log_level_combo.currentText(),
            ip_rediscovery_enabled=self.rediscover_check.isChecked(),
        )


class DeviceInfoDialog(QDialog):
    """Read-only summary of a camera's connection details."""

    def __init__(self, parent: Optional[QWidget], camera: Camera,
                 status: str = "—", mac: str = "",
                 last_seen: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Cihaz Bilgisi")
        self.setModal(True)
        self.setMinimumWidth(420)

        title = QLabel(camera.name or camera.host or "Kamera")
        title.setObjectName("TitleLabel")

        subtitle = QLabel(
            "Bu kameranın yapılandırma ve bağlantı bilgileri."
        )
        subtitle.setObjectName("MutedLabel")
        subtitle.setWordWrap(True)

        sep = QFrame()
        sep.setObjectName("Separator")
        sep.setFrameShape(QFrame.Shape.HLine)

        rtsp_url = camera.rtsp_url
        # Mask the password in RTSP URLs so they're safe to copy.
        masked_url = rtsp_url
        if camera.password and not camera.use_custom_url:
            masked_url = rtsp_url.replace(camera.password, "•" * len(camera.password))

        rows: list[tuple[str, str]] = [
            ("Ad", camera.name or "—"),
            ("Host / IP", camera.host or "—"),
            ("Kullanıcı", camera.username or "—"),
            ("RTSP portu", str(camera.rtsp_port)),
            ("ONVIF portu", str(camera.onvif_port)),
            ("Akış", camera.stream),
            ("Özel URL", "Evet" if camera.use_custom_url else "Hayır"),
            ("Ses", "Açık" if camera.audio_enabled else "Kapalı"),
            ("MAC adresi", mac or "—"),
            ("Son görülen IP", last_seen or "—"),
            ("Durum", status or "—"),
            ("RTSP", masked_url or "—"),
        ]

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        for label, value in rows:
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            value_label.setWordWrap(True)
            form.addRow(label, value_label)

        close_btn = QPushButton("Kapat")
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(self.accept)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(sep)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addLayout(button_row)
