"""PTZ control panel: direction arrows and preset list.

The panel is bound to one camera at a time via :meth:`set_camera`. It owns
the active :class:`PtzController` and tears it down when the camera changes
or the panel is closed. The panel hides itself when no camera is bound.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import Camera
from .onvif_ptz import PtzController, PtzPreset


PAN_SPEED = 0.5
TILT_SPEED = 0.5


class HoldButton(QPushButton):
    """Button that emits ``held`` on press and ``released_`` on release.

    Used for continuous PTZ movement: start moving on press, stop on release.
    """

    held = pyqtSignal()
    released_ = pyqtSignal()

    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(label, parent)
        self.setAutoDefault(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pressed.connect(self.held.emit)
        self.released.connect(self.released_.emit)


class PtzPanel(QWidget):
    """PTZ control panel bound to a single camera. Hidden when unbound."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._camera: Optional[Camera] = None
        self._controller: Optional[PtzController] = None
        self._supported: bool = False
        self._presets: list[PtzPreset] = []

        self._build_ui()
        self._update_enabled_state()
        self.setVisible(False)

    # -------------------- UI --------------------

    def _build_ui(self) -> None:
        section = QLabel("Hareket")
        section.setObjectName("SectionLabel")
        section.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._name_label = QLabel("")
        self._name_label.setObjectName("PtzCameraName")
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setWordWrap(True)

        self._status = QLabel("")
        self._status.setObjectName("MutedLabel")
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Direction pad (3x3 grid: only the cross is filled).
        pad = QWidget()
        pad_layout = QGridLayout(pad)
        pad_layout.setContentsMargins(0, 0, 0, 0)
        pad_layout.setSpacing(6)

        self._btn_up = HoldButton("↑")
        self._btn_down = HoldButton("↓")
        self._btn_left = HoldButton("←")
        self._btn_right = HoldButton("→")
        self._btn_home = QPushButton("⌂")
        self._btn_home.setToolTip("Durdur")
        self._btn_home.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_home.setAutoDefault(False)

        for b in (self._btn_up, self._btn_down, self._btn_left, self._btn_right, self._btn_home):
            b.setObjectName("PtzButton")
            b.setFixedSize(44, 40)

        pad_layout.addWidget(self._btn_up, 0, 1)
        pad_layout.addWidget(self._btn_left, 1, 0)
        pad_layout.addWidget(self._btn_home, 1, 1)
        pad_layout.addWidget(self._btn_right, 1, 2)
        pad_layout.addWidget(self._btn_down, 2, 1)

        # Center the pad horizontally inside the sidebar.
        pad_row = QHBoxLayout()
        pad_row.addStretch(1)
        pad_row.addWidget(pad)
        pad_row.addStretch(1)

        # Preset row.
        preset_label = QLabel("Konumlar")
        preset_label.setObjectName("SectionLabel")
        preset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preset_combo = QComboBox()
        self._preset_combo.setPlaceholderText("Konum yok")
        self._btn_goto = QPushButton("Git")
        self._btn_goto.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_goto.setAutoDefault(False)
        self._btn_goto.clicked.connect(self._on_goto_preset)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_row.addWidget(self._preset_combo, 1)
        preset_row.addWidget(self._btn_goto)

        # Container layout (centered).
        container = QFrame()
        container.setObjectName("PtzPanel")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(section)
        layout.addWidget(self._name_label)
        layout.addWidget(self._status)
        layout.addLayout(pad_row)
        layout.addWidget(preset_label)
        layout.addLayout(preset_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(container)

        # Wire movement buttons.
        self._btn_up.held.connect(lambda: self._move(0.0, TILT_SPEED, 0.0))
        self._btn_down.held.connect(lambda: self._move(0.0, -TILT_SPEED, 0.0))
        self._btn_left.held.connect(lambda: self._move(-PAN_SPEED, 0.0, 0.0))
        self._btn_right.held.connect(lambda: self._move(PAN_SPEED, 0.0, 0.0))

        for hb in (self._btn_up, self._btn_down, self._btn_left, self._btn_right):
            hb.released_.connect(self._stop)

        self._btn_home.clicked.connect(self._stop)

    # -------------------- Public API --------------------

    def set_camera(self, camera: Optional[Camera]) -> None:
        if camera is None and self._camera is None:
            self.setVisible(False)
            return
        if camera is not None and self._camera is not None and camera.id == self._camera.id:
            # Only refresh credentials if they changed.
            if (camera.host == self._camera.host
                    and camera.onvif_port == self._camera.onvif_port
                    and camera.username == self._camera.username
                    and camera.password == self._camera.password):
                self._camera = camera
                self._name_label.setText(camera.name or camera.host)
                return

        self._teardown_controller()
        self._camera = camera
        self._supported = False
        self._presets = []
        self._preset_combo.clear()

        if camera is None:
            self._name_label.setText("")
            self._status.setText("")
            self._update_enabled_state()
            self.setVisible(False)
            return

        self.setVisible(True)
        self._name_label.setText(camera.name or camera.host)

        if not camera.host:
            self._status.setText("Host bilgisi yok, ONVIF kullanılamaz")
            self._update_enabled_state()
            return

        self._status.setText("ONVIF bağlanıyor...")
        self._controller = PtzController(
            host=camera.host,
            port=camera.onvif_port,
            username=camera.username,
            password=camera.password,
            parent=self,
        )
        self._controller.capabilities_ready.connect(self._on_capabilities)
        self._controller.presets_ready.connect(self._on_presets)
        self._controller.error.connect(self._on_error)
        self._controller.initialize()
        self._update_enabled_state()

    def shutdown(self) -> None:
        self._teardown_controller()

    # -------------------- internal --------------------

    def _teardown_controller(self) -> None:
        if self._controller is not None:
            try:
                self._controller.shutdown()
            except Exception:
                pass
            self._controller.deleteLater()
            self._controller = None

    def _on_capabilities(self, supported: bool, message: str) -> None:
        self._supported = supported
        self._status.setText(message)
        self._update_enabled_state()

    def _on_presets(self, presets: list) -> None:
        self._presets = list(presets)
        self._preset_combo.clear()
        for p in self._presets:
            self._preset_combo.addItem(p.name, p.token)
        self._update_enabled_state()

    def _on_error(self, message: str) -> None:
        self._status.setText(message)

    def _move(self, pan: float, tilt: float, zoom: float) -> None:
        if self._controller is None or not self._supported:
            return
        self._controller.move(pan, tilt, zoom)

    def _stop(self) -> None:
        if self._controller is None or not self._supported:
            return
        self._controller.stop_move()

    def _on_goto_preset(self) -> None:
        if self._controller is None or not self._supported:
            return
        token = self._preset_combo.currentData()
        if token:
            self._controller.goto_preset(token)

    def _update_enabled_state(self) -> None:
        movable = self._supported and self._controller is not None
        for b in (self._btn_up, self._btn_down, self._btn_left,
                  self._btn_right, self._btn_home):
            b.setEnabled(movable)
        has_preset = movable and self._preset_combo.count() > 0
        self._preset_combo.setEnabled(has_preset)
        self._btn_goto.setEnabled(has_preset)
