"""Main application window: collapsible sidebar + camera grid."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QShortcut,
)
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
from .dialogs import CameraDialog, DeviceInfoDialog, SettingsDialog
from .logger import configure_logging, get_logger
from .network_scan import (
    IpRediscoverer,
    RediscoveryResult,
    fingerprint_camera_mac,
    schedule_ip_rediscovery,
)
from .onvif_ptz import PtzManager
from .ptz_panel import PtzPanel
from .resource_monitor import ResourceMonitor


_log = get_logger("main_window")


class ChevronToggleButton(QPushButton):
    """Sidebar toggle button that paints its own chevron, perfectly centered.

    Relying on a unicode glyph for the arrow makes vertical centering very
    font-dependent — the angle quotation marks shift visibly in many fonts.
    Drawing the chevron with QPainter keeps it pixel-centered regardless.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed: bool = False

    def set_collapsed(self, collapsed: bool) -> None:
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        # Let the stylesheet paint the background / border / hover state.
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        cx = rect.center().x() + 0.5
        cy = rect.center().y() + 0.5
        size = 7.0
        # When expanded, point left ("‹"); when collapsed, point right ("›").
        if self._collapsed:
            tip = QPointF(cx + size * 0.55, cy)
            top = QPointF(cx - size * 0.55, cy - size)
            bot = QPointF(cx - size * 0.55, cy + size)
        else:
            tip = QPointF(cx - size * 0.55, cy)
            top = QPointF(cx + size * 0.55, cy - size)
            bot = QPointF(cx + size * 0.55, cy + size)
        pen = QPen(self.palette().windowText().color())
        # Pick a color that contrasts both the dark and accent button states.
        color = QColor("#ffffff") if self.underMouse() else QColor("#f2f2f7")
        pen.setColor(color)
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(top, tip)
        painter.drawLine(tip, bot)


SIDEBAR_WIDTH = 280
# Wide enough that the 40 px toggle button fills the content area exactly,
# leaving the button visually centred when the sidebar is collapsed.
SIDEBAR_COLLAPSED_WIDTH = 56
TOGGLE_BUTTON_SIZE = 40


class MainWindow(QMainWindow):
    # Internal signal used to marshal results from the daemon MAC
    # fingerprint thread back to the UI thread (Qt routes signals across
    # threads via a queued connection by default).
    _mac_fingerprinted = pyqtSignal(str, str, str)  # camera_id, mac, host

    def __init__(self, preloaded_config: AppConfig | None = None,
                 splash=None) -> None:
        super().__init__()
        self.setWindowTitle("Tapo Viewer")
        self.resize(1280, 800)
        self.setMinimumSize(QSize(720, 600))

        self._config: AppConfig = preloaded_config or load_config()
        self._collapsed: bool = bool(self._config.settings.sidebar_collapsed)
        self._splash = splash

        # Apply file logging straight away so the rest of the window — and
        # any background workers it starts — emit through the configured
        # handler.
        configure_logging(
            enabled=self._config.settings.logging_enabled,
            level=self._config.settings.log_level,
        )
        _log.info("Tapo Viewer starting (cameras=%d)", len(self._config.cameras))

        # In-flight rediscovery jobs, keyed by camera id, so we don't kick
        # off two scans for the same camera at the same time.
        self._rediscoverers: dict[str, IpRediscoverer] = {}
        # Tile status the last time we saw it, so we only react when a
        # camera transitions online → offline.
        self._last_tile_status: dict[str, str] = {}
        # Fingerprint workers in progress, by camera id, so we don't spawn
        # duplicates while one is still running.
        self._mac_workers_active: set[str] = set()
        self._mac_fingerprinted.connect(self._on_mac_fingerprinted)

        # ---- Sidebar shell ----
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(
            SIDEBAR_COLLAPSED_WIDTH if self._collapsed else SIDEBAR_WIDTH
        )

        # Header row: title + toggle button.
        self.toggle_btn = ChevronToggleButton()
        self.toggle_btn.setObjectName("ToggleButton")
        self.toggle_btn.setFixedSize(TOGGLE_BUTTON_SIZE, TOGGLE_BUTTON_SIZE)
        self.toggle_btn.setToolTip("Kenar çubuğunu daralt/genişlet")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle_sidebar)

        self.title_label = QLabel("Tapo Viewer")
        self.title_label.setObjectName("TitleLabel")

        # Header row layout is rebuilt on collapse/expand so the toggle
        # button sits flush-left with the title (expanded) or perfectly
        # centred on its own (collapsed).
        self._header_row = QHBoxLayout()
        self._header_row.setContentsMargins(0, 0, 0, 0)
        self._header_row.setSpacing(10)

        # Body widgets (hidden when collapsed).
        self.cameras_label = QLabel("Kameralar")
        self.cameras_label.setObjectName("SectionLabel")

        self.list_widget = CameraList()
        self.list_widget.selection_changed.connect(self._on_list_selection)
        self.list_widget.item_double_clicked_id.connect(self._on_list_double_clicked)
        self.list_widget.customContextMenuRequested.connect(self._on_list_context_menu)
        self.list_widget.order_changed.connect(self._on_order_changed)
        self.list_widget.mute_toggled.connect(self._on_mute_toggled)
        self.list_widget.visibility_toggled.connect(self._on_visibility_toggled)
        self.list_widget.overflow_menu_requested.connect(self._on_overflow_menu)

        self.add_btn = QPushButton("+ Kamera Ekle")
        self.add_btn.setObjectName("PrimaryButton")
        self.add_btn.clicked.connect(self._on_add_camera)

        self.restore_btn = QPushButton("Tüm Izgara")
        self.restore_btn.clicked.connect(self._on_restore)
        self.restore_btn.setEnabled(False)

        self.settings_btn = QPushButton("Ayarlar")
        self.settings_btn.clicked.connect(self._on_open_settings)

        # PTZ manager spins up an ONVIF controller per camera ahead of time
        # so opening the panel feels instant.
        self.ptz_manager = PtzManager(self)

        # PTZ panel.
        self.ptz_panel = PtzPanel(manager=self.ptz_manager)

        # Layout.
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 12)
        sidebar_layout.setSpacing(8)
        sidebar_layout.addLayout(self._header_row)

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
        self.grid.tile_status_changed.connect(self._on_tile_status_changed)
        if self._splash is not None:
            self.grid.tile_first_frame.connect(self._splash.mark_camera_ready)

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
        self.grid.set_cameras(self._visible_cameras())
        # Kick off ONVIF discovery for every camera right away so PTZ is
        # ready before the user clicks anything.
        self.ptz_manager.sync(self._config.cameras)
        self._apply_collapsed_state()
        self._update_status()
        self.ptz_panel.set_camera(None)

    # -- helpers --

    def _refresh_camera_list(self, selected_id: str | None = None) -> None:
        if selected_id is None:
            selected_id = self.list_widget.selected_camera_id()
        self.list_widget.populate(self._config.cameras, selected_id=selected_id)

    def _visible_cameras(self) -> list[Camera]:
        """Subset of the configured cameras that should appear in the grid.

        Cameras the user has toggled off in the sidebar still live in the
        configuration (so they can be restored with one click) but never
        reach :class:`CameraGrid`, which means their stream worker is
        stopped — exactly what the user asked for when they hide a feed.
        """
        return [c for c in self._config.cameras if getattr(c, "visible", True)]

    def _camera_by_id(self, cam_id: str | None) -> Camera | None:
        if not cam_id:
            return None
        return next((c for c in self._config.cameras if c.id == cam_id), None)

    def _selected_camera(self) -> Camera | None:
        return self._camera_by_id(self.list_widget.selected_camera_id())

    def _save(self) -> None:
        save_config(self._config)

    def _update_status(self) -> None:
        total = len(self._config.cameras)
        visible = len(self._visible_cameras())
        cols = self._config.settings.grid_columns
        rows = max(1, (visible + cols - 1) // cols) if visible else 1
        if visible == total:
            count_text = f"{total} kamera"
        else:
            count_text = f"{visible} / {total} kamera (gizli: {total - visible})"
        self._status_label.setText(
            f"{count_text}   ·   {cols}×{rows} ızgara   ·   {self._config.settings.target_fps} FPS"
        )

    def _apply_collapsed_state(self) -> None:
        self.sidebar.setFixedWidth(
            SIDEBAR_COLLAPSED_WIDTH if self._collapsed else SIDEBAR_WIDTH
        )
        self.body_widget.setVisible(not self._collapsed)
        self.title_label.setVisible(not self._collapsed)
        # Custom-painted chevron stays perfectly centred regardless of font.
        self.toggle_btn.set_collapsed(self._collapsed)
        self.toggle_btn.setToolTip(
            "Kenar çubuğunu genişlet" if self._collapsed else "Kenar çubuğunu daralt"
        )
        # Rebuild the header row so the toggle button is perfectly centred
        # when collapsed (stretches on both sides) and flush-left next to the
        # title when expanded.
        while self._header_row.count():
            self._header_row.takeAt(0)
        if self._collapsed:
            self._header_row.addStretch(1)
            self._header_row.addWidget(self.toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self._header_row.addStretch(1)
        else:
            self._header_row.addWidget(self.toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self._header_row.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)

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
        self._open_camera_menu(self.list_widget.viewport().mapToGlobal(pos))

    def _on_overflow_menu(self, camera_id: str, global_pos: QPoint) -> None:
        if camera_id and self.list_widget.selected_camera_id() != camera_id:
            self.list_widget.select_by_id(camera_id)
        self._open_camera_menu(global_pos)

    def _open_camera_menu(self, global_pos: QPoint) -> None:
        cam = self._selected_camera()
        if cam is None:
            return
        menu = QMenu(self)
        info_act = QAction("Bilgi", self)
        info_act.triggered.connect(self._on_show_device_info)
        edit_act = QAction("Düzenle", self)
        edit_act.triggered.connect(self._on_edit_camera)
        rediscover_act = QAction("Yerel ağda yeniden bul", self)
        rediscover_act.setEnabled(bool(cam.mac_address)
                                  and self._config.settings.ip_rediscovery_enabled)
        rediscover_act.triggered.connect(self._on_manual_rediscover)
        remove_act = QAction("Kaldır", self)
        remove_act.triggered.connect(self._on_remove_camera)
        menu.addAction(info_act)
        menu.addAction(edit_act)
        menu.addAction(rediscover_act)
        menu.addSeparator()
        menu.addAction(remove_act)
        menu.exec(global_pos)

    def _on_show_device_info(self) -> None:
        cam = self._selected_camera()
        if cam is None:
            return
        status = self._last_tile_status.get(cam.id, "—")
        dlg = DeviceInfoDialog(self, cam,
                               status=self._humanize_status(status),
                               mac=cam.mac_address,
                               last_seen=cam.last_seen_host)
        dlg.exec()

    @staticmethod
    def _humanize_status(status: str) -> str:
        return {
            "connecting": "Bağlanıyor",
            "online":     "Bağlı",
            "offline":    "Bağlantı yok",
            "error":      "Hata",
            "idle":       "Bekleniyor",
        }.get(status, status or "—")

    def _on_manual_rediscover(self) -> None:
        cam = self._selected_camera()
        if cam is None:
            return
        if not cam.mac_address:
            QMessageBox.information(
                self,
                "Yeniden bul",
                "Bu kamera için MAC adresi henüz öğrenilmemiş. "
                "Kamera bir kez bağlandıktan sonra yeniden deneyin.",
            )
            return
        self._kick_rediscovery(cam, reason="manual")

    def _on_order_changed(self, ordered_ids: list) -> None:
        by_id = {c.id: c for c in self._config.cameras}
        new_order = [by_id[i] for i in ordered_ids if i in by_id]
        # Append anything missing (shouldn't happen, but stay safe).
        for c in self._config.cameras:
            if c.id not in ordered_ids:
                new_order.append(c)
        self._config.cameras = new_order
        self._save()
        # Rebuild the sidebar list. QListWidget's InternalMove drop destroys
        # the original QListWidgetItem and creates a new one at the
        # destination, which orphans the CameraRow we attached via
        # setItemWidget(). Without a fresh populate() the second drag hits
        # those dangling references and the UI freezes.
        self._refresh_camera_list(selected_id=self.list_widget.selected_camera_id())
        self.grid.set_cameras(self._visible_cameras())
        self.ptz_manager.sync(self._config.cameras)
        self._update_status()

    def _on_mute_toggled(self, camera_id: str, audio_enabled: bool) -> None:
        for cam in self._config.cameras:
            if cam.id == camera_id:
                cam.audio_enabled = audio_enabled
                break
        self._save()
        self.grid.set_cameras(self._visible_cameras())

    def _on_visibility_toggled(self, camera_id: str, visible: bool) -> None:
        cam = self._camera_by_id(camera_id)
        if cam is None or cam.visible == visible:
            return
        cam.visible = visible
        self._save()
        self._update_status()
        # Defer the grid rebuild (which tears down the camera's RTSP
        # worker, audio backend and tile widget when hiding) to the next
        # event-loop tick. Doing it inline crashed the process because we
        # were still inside the QPushButton click handler that fired the
        # ``visibility_toggled`` signal — Qt's button state machine, our
        # libVLC teardown and the deleteLater chain do not survive being
        # interleaved on the same call stack on Windows. Same trick the
        # drag-and-drop reorder code uses (`_on_rows_moved`).
        QTimer.singleShot(
            0,
            lambda cid=camera_id, v=visible: self._apply_visibility_change(cid, v),
        )

    def _apply_visibility_change(self, camera_id: str, visible: bool) -> None:
        # Re-check: the user might have toggled again while we were queued.
        cam = self._camera_by_id(camera_id)
        if cam is None or cam.visible != visible:
            return
        self.grid.set_cameras(self._visible_cameras())
        # If the now-hidden camera was the selected one, drop the PTZ panel.
        if not visible and self.list_widget.selected_camera_id() == camera_id:
            self.ptz_panel.set_camera(None)
        self._update_status()

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
            self.grid.set_cameras(self._visible_cameras())
            self.ptz_manager.sync(self._config.cameras)
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
            self.grid.set_cameras(self._visible_cameras())
            self.ptz_manager.sync(self._config.cameras)
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
        self.grid.set_cameras(self._visible_cameras())
        self.ptz_manager.remove(cam.id)
        self.ptz_manager.sync(self._config.cameras)
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
            configure_logging(
                enabled=new_settings.logging_enabled,
                level=new_settings.log_level,
            )
            _log.info("Settings updated: logging=%s level=%s rediscover=%s",
                      new_settings.logging_enabled,
                      new_settings.log_level,
                      new_settings.ip_rediscovery_enabled)
            self._update_status()

    def _on_tile_status_changed(self, camera_id: str, status: str) -> None:
        prev = self._last_tile_status.get(camera_id)
        self._last_tile_status[camera_id] = status
        # Tell the splash about cameras that failed their first connect
        # attempt so it can close even when an unreachable camera never
        # produces a frame. Successful connects are handled via the
        # ``tile_first_frame`` signal.
        if (self._splash is not None
                and status in ("offline", "error")
                and prev in (None, "connecting")):
            self._splash.mark_camera_failed(camera_id)
        if prev == status:
            return
        cam = self._camera_by_id(camera_id)
        if cam is None:
            return
        if status == "online":
            # First successful connect — capture the MAC for future
            # rediscovery, but only if we don't already have one for this
            # configured host.
            self._capture_mac(cam)
        elif status in ("offline", "error") and prev == "online":
            # Lost a previously-working connection. If MAC rediscovery is
            # enabled, kick a scan; if it finds a new IP we'll reconnect.
            if self._config.settings.ip_rediscovery_enabled and cam.mac_address:
                self._kick_rediscovery(cam, reason="offline")

    def _capture_mac(self, cam: Camera) -> None:
        if cam.use_custom_url or not cam.host:
            return
        # Already have a MAC for this exact host — don't re-fingerprint
        # repeatedly.
        if cam.mac_address and cam.last_seen_host == cam.host:
            return
        if cam.id in self._mac_workers_active:
            return
        self._mac_workers_active.add(cam.id)
        cam_id = cam.id
        host = cam.host
        signal = self._mac_fingerprinted

        def worker() -> None:
            try:
                mac = fingerprint_camera_mac(host)
            except Exception:  # pragma: no cover - defensive
                mac = ""
            # Emit even on failure so we can clear the active flag on the
            # UI thread. Qt delivers cross-thread signals via the receiver's
            # event loop, which is what makes touching ``_config`` here safe.
            signal.emit(cam_id, mac, host)

        from threading import Thread
        Thread(target=worker, daemon=True, name="mac-fingerprint").start()

    def _on_mac_fingerprinted(self, camera_id: str, mac: str,
                               host: str) -> None:
        self._mac_workers_active.discard(camera_id)
        if not mac:
            return
        cam = self._camera_by_id(camera_id)
        if cam is None or cam.host != host:
            # Camera was removed or its host changed while we were
            # fingerprinting — discard the result.
            return
        self._update_camera_fields(camera_id, mac=mac, last_seen=host)

    def _update_camera_fields(self, camera_id: str, *,
                              mac: str | None = None,
                              last_seen: str | None = None,
                              host: str | None = None) -> None:
        for cam in self._config.cameras:
            if cam.id != camera_id:
                continue
            changed = False
            if mac is not None and cam.mac_address != mac:
                cam.mac_address = mac
                changed = True
            if last_seen is not None and cam.last_seen_host != last_seen:
                cam.last_seen_host = last_seen
                changed = True
            if host is not None and cam.host != host:
                cam.host = host
                changed = True
            if changed:
                self._save()
                _log.info("Camera %s updated: mac=%s last_seen=%s host=%s",
                          camera_id, cam.mac_address,
                          cam.last_seen_host, cam.host)
            return

    def _kick_rediscovery(self, cam: Camera, *, reason: str) -> None:
        if cam.id in self._rediscoverers:
            return
        if not cam.mac_address:
            return
        _log.info("Starting IP rediscovery for %s (%s) reason=%s",
                  cam.id, cam.host, reason)
        self._status_label.setText(
            f"\"{cam.name}\" için MAC adresine göre IP aranıyor..."
        )
        scanner = schedule_ip_rediscovery(
            self,
            camera_id=cam.id,
            mac=cam.mac_address,
            rtsp_port=cam.rtsp_port,
            last_host=cam.host,
            on_result=self._on_rediscovery_done,
        )
        if scanner is not None:
            self._rediscoverers[cam.id] = scanner

    def _on_rediscovery_done(self, result: RediscoveryResult) -> None:
        scanner = self._rediscoverers.pop(result.camera_id, None)
        if scanner is not None:
            scanner.deleteLater()
        cam = self._camera_by_id(result.camera_id)
        if cam is None:
            self._update_status()
            return
        if not result.new_host:
            _log.info("Rediscovery failed for %s (%s)", cam.id, cam.host)
            self._status_label.setText(
                f"\"{cam.name}\" yerel ağda bulunamadı."
            )
            return
        if result.new_host == cam.host:
            self._update_status()
            return
        _log.info("Rediscovery moved %s from %s to %s",
                  cam.id, cam.host, result.new_host)
        old_host = cam.host
        self._update_camera_fields(cam.id,
                                    host=result.new_host,
                                    last_seen=result.new_host)
        # Refresh dependent widgets so the new host takes effect immediately.
        self._refresh_camera_list(selected_id=self.list_widget.selected_camera_id())
        self.grid.set_cameras(self._visible_cameras())
        self.ptz_manager.sync(self._config.cameras)
        self._status_label.setText(
            f"\"{cam.name}\" yeni IP adresinde bulundu: {old_host} → {result.new_host}"
        )

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
        self.ptz_manager.shutdown()
        self.grid.stop_all_and_wait()
        self._resource_monitor.shutdown()
        self._save()
        super().closeEvent(event)
