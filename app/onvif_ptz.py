"""ONVIF PTZ controller running on a background thread.

All ONVIF/SOAP calls are blocking, so they live in a worker on its own
QThread. The controller exposes Qt signals for capabilities/presets/errors
and slots (via signals) for movement/stop/preset commands.

Controllers are typically created once per camera at app startup (see
:class:`PtzManager`) so the PTZ panel can be displayed instantly when a
camera is selected — capability/preset discovery has already happened in
the background by then.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from .logger import get_logger

try:
    from PyQt6 import sip  # type: ignore
except ImportError:  # pragma: no cover - sip ships with PyQt6
    sip = None  # type: ignore


_log = get_logger("ptz")


# Same graveyard trick :mod:`camera_tile` uses — keep worker + thread
# alive after the controller goes out of scope, so PyQt's C++
# destructor for ``QThread`` doesn't fire while ``run()`` is still on
# the stack (which crashes the process on Windows).
_PTZ_GRAVEYARD: set = set()


def _bury_ptz_thread(worker: object, thread: object) -> None:
    if sip is not None:
        for obj in (worker, thread):
            try:
                sip.transferto(obj, None)
            except (TypeError, ValueError):
                pass
        return
    _PTZ_GRAVEYARD.add((worker, thread))


@dataclass
class PtzPreset:
    token: str
    name: str


class _PtzWorker(QObject):
    capabilities_ready = pyqtSignal(bool, str)  # supported, message
    presets_ready = pyqtSignal(list)            # list[PtzPreset]
    error = pyqtSignal(str)

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._cam = None
        self._ptz = None
        self._profile_token: Optional[str] = None
        self._supported = False

    @pyqtSlot()
    def initialize(self) -> None:
        _log.info("PTZ init %s:%s user=%s", self._host, self._port, self._username)
        try:
            from onvif import ONVIFCamera  # type: ignore
        except Exception as exc:  # pragma: no cover - import error path
            _log.error("onvif-zeep import failed: %s", exc)
            self._supported = False
            self.capabilities_ready.emit(False, f"onvif-zeep yüklü değil: {exc}")
            return

        try:
            cam = ONVIFCamera(self._host, self._port, self._username, self._password)
            media = cam.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                _log.warning("PTZ %s: no ONVIF media profiles", self._host)
                self._supported = False
                self.capabilities_ready.emit(False, "ONVIF medya profili bulunamadı")
                return
            profile = profiles[0]
            _log.debug("PTZ %s: using profile token=%s", self._host, profile.token)
            ptz_config = getattr(profile, "PTZConfiguration", None)
            if ptz_config is None:
                _log.info("PTZ %s: profile has no PTZConfiguration", self._host)
                self._supported = False
                self.capabilities_ready.emit(False, "Kamera PTZ desteklemiyor")
                return
            ptz = cam.create_ptz_service()
            self._cam = cam
            self._ptz = ptz
            self._profile_token = profile.token
            self._supported = True
            _log.info("PTZ %s: capabilities ready, profile_token=%s",
                      self._host, profile.token)
            self.capabilities_ready.emit(True, "Hareket destekleniyor")
            self._load_presets()
        except Exception as exc:
            _log.exception("PTZ %s: init failed", self._host)
            self._supported = False
            self.capabilities_ready.emit(False, f"ONVIF bağlantısı başarısız: {exc}")

    def _load_presets(self) -> None:
        if not self._supported or self._ptz is None:
            return
        try:
            req = self._ptz.create_type("GetPresets")
            req.ProfileToken = self._profile_token
            presets = self._ptz.GetPresets(req) or []
            result = [
                PtzPreset(token=p.token, name=(getattr(p, "Name", "") or p.token))
                for p in presets
            ]
            _log.info("PTZ %s: %d preset(s) loaded", self._host, len(result))
            self.presets_ready.emit(result)
        except Exception as exc:
            _log.warning("PTZ %s: preset load failed: %s", self._host, exc)
            self.error.emit(f"Preset listesi alınamadı: {exc}")

    @pyqtSlot(float, float, float)
    def continuous_move(self, pan: float, tilt: float, zoom: float) -> None:
        if not self._supported or self._ptz is None:
            _log.debug("PTZ %s: move ignored (not ready)", self._host)
            return
        _log.debug("PTZ %s: continuous_move pan=%.2f tilt=%.2f zoom=%.2f",
                   self._host, pan, tilt, zoom)
        try:
            req = self._ptz.create_type("ContinuousMove")
            req.ProfileToken = self._profile_token
            req.Velocity = {
                "PanTilt": {"x": pan, "y": tilt},
                "Zoom": {"x": zoom},
            }
            self._ptz.ContinuousMove(req)
        except Exception as exc:
            _log.warning("PTZ %s: continuous_move failed: %s", self._host, exc)
            self.error.emit(f"Hareket hatası: {exc}")

    @pyqtSlot()
    def stop_move(self) -> None:
        if not self._supported or self._ptz is None:
            return
        _log.debug("PTZ %s: stop", self._host)
        try:
            req = self._ptz.create_type("Stop")
            req.ProfileToken = self._profile_token
            req.PanTilt = True
            req.Zoom = True
            self._ptz.Stop(req)
        except Exception as exc:
            _log.warning("PTZ %s: stop failed: %s", self._host, exc)
            self.error.emit(f"Durdurma hatası: {exc}")

    @pyqtSlot(str)
    def goto_preset(self, token: str) -> None:
        if not self._supported or self._ptz is None:
            return
        _log.debug("PTZ %s: goto_preset token=%s", self._host, token)
        try:
            req = self._ptz.create_type("GotoPreset")
            req.ProfileToken = self._profile_token
            req.PresetToken = token
            self._ptz.GotoPreset(req)
        except Exception as exc:
            _log.warning("PTZ %s: goto_preset failed: %s", self._host, exc)
            self.error.emit(f"Preset gidiş hatası: {exc}")


class PtzController(QObject):
    """Public PTZ controller. Owns a worker thread."""

    capabilities_ready = pyqtSignal(bool, str)
    presets_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    # Internal cross-thread signals to invoke worker slots.
    _request_init = pyqtSignal()
    _request_move = pyqtSignal(float, float, float)
    _request_stop = pyqtSignal()
    _request_goto = pyqtSignal(str)

    def __init__(self, host: str, port: int, username: str, password: str,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._thread = QThread()
        self._worker = _PtzWorker(host, port, username, password)
        self._worker.moveToThread(self._thread)

        # Cache last-known capabilities/presets so a new subscriber gets the
        # current state immediately on connect, even if discovery already
        # finished in the background.
        self._cap_supported: Optional[bool] = None
        self._cap_message: str = ""
        self._presets_cache: list = []

        self._worker.capabilities_ready.connect(self._on_caps)
        self._worker.presets_ready.connect(self._on_presets)
        self._worker.error.connect(self.error)

        self._request_init.connect(self._worker.initialize)
        self._request_move.connect(self._worker.continuous_move)
        self._request_stop.connect(self._worker.stop_move)
        self._request_goto.connect(self._worker.goto_preset)

        self._thread.start()

    @property
    def credentials(self) -> tuple[str, int, str, str]:
        return (self._host, self._port, self._username, self._password)

    def initialize(self) -> None:
        self._request_init.emit()

    def emit_cached_state(self) -> None:
        """Re-emit the last known capabilities/presets for new listeners."""
        if self._cap_supported is not None:
            self.capabilities_ready.emit(self._cap_supported, self._cap_message)
        if self._presets_cache:
            self.presets_ready.emit(list(self._presets_cache))

    def _on_caps(self, supported: bool, message: str) -> None:
        self._cap_supported = supported
        self._cap_message = message
        self.capabilities_ready.emit(supported, message)

    def _on_presets(self, presets: list) -> None:
        self._presets_cache = list(presets)
        self.presets_ready.emit(list(presets))

    def move(self, pan: float, tilt: float, zoom: float = 0.0) -> None:
        _log.debug("PTZ %s: controller.move → worker (pan=%.2f tilt=%.2f zoom=%.2f)",
                   self._host, pan, tilt, zoom)
        self._request_move.emit(pan, tilt, zoom)

    def stop_move(self) -> None:
        _log.debug("PTZ %s: controller.stop_move → worker", self._host)
        self._request_stop.emit()

    def goto_preset(self, token: str) -> None:
        _log.debug("PTZ %s: controller.goto_preset(%s) → worker", self._host, token)
        self._request_goto.emit(token)

    def shutdown(self, block_ms: int = 0) -> None:
        """Ask the worker thread to exit.

        By default ``block_ms=0`` — quit the event loop and return
        immediately. Blocking the UI on ``thread.wait`` during
        ``ptz_manager.remove()`` (which happens on the click stack of
        the "Kaldır" menu action) held the window frozen for 2 s per
        camera and, in the worst case, crashed the app because queued
        signals from the still-running SOAP call landed on a
        half-destroyed controller. Passing a positive ``block_ms`` is
        reserved for graceful app shutdown where a brief wait is
        acceptable.

        We also transfer the Python ownership of the worker + thread
        to Qt with ``sip.transferto`` — otherwise dropping the
        controller reference could destroy the C++ ``QThread`` while
        the ONVIF SOAP call is still in flight.
        """
        try:
            self._request_stop.emit()
        except Exception:
            pass
        self._thread.quit()
        if block_ms > 0 and self._thread.wait(block_ms):
            # Thread finished cleanly — Python is safe to drop refs.
            return
        # Still running or block_ms == 0. Bury it so PyQt's sip layer
        # doesn't fire ~QThread() while run() is still executing.
        _bury_ptz_thread(self._worker, self._thread)


class PtzManager(QObject):
    """Owns one :class:`PtzController` per camera id and starts ONVIF
    discovery for every camera up-front, so the PTZ panel never has to
    wait for a SOAP handshake when a camera is selected.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._controllers: dict[str, PtzController] = {}

    def ensure(self, camera) -> Optional[PtzController]:
        """Return (creating if necessary) the controller for ``camera``.

        If credentials changed since last call, the old controller is
        torn down and a fresh one is created.
        """
        if not camera or not camera.host:
            return None
        existing = self._controllers.get(camera.id)
        if existing is not None:
            host, port, user, pw = existing.credentials
            if (host == camera.host and port == camera.onvif_port
                    and user == camera.username and pw == camera.password):
                return existing
            # Credentials changed — tear down and rebuild.
            existing.shutdown()
            existing.deleteLater()
            del self._controllers[camera.id]
        ctrl = PtzController(
            host=camera.host,
            port=camera.onvif_port,
            username=camera.username,
            password=camera.password,
            parent=self,
        )
        self._controllers[camera.id] = ctrl
        ctrl.initialize()
        return ctrl

    def get(self, camera_id: str) -> Optional[PtzController]:
        return self._controllers.get(camera_id)

    def remove(self, camera_id: str) -> None:
        ctrl = self._controllers.pop(camera_id, None)
        if ctrl is not None:
            ctrl.shutdown()
            ctrl.deleteLater()

    def sync(self, cameras: list) -> None:
        """Spin up controllers for new cameras, drop ones that vanished."""
        wanted_ids = {c.id for c in cameras}
        for cam_id in list(self._controllers.keys()):
            if cam_id not in wanted_ids:
                self.remove(cam_id)
        for cam in cameras:
            self.ensure(cam)

    def shutdown(self) -> None:
        """Tear down every PTZ controller.

        Fire ``quit`` on every worker thread first (non-blocking), then
        run a short wait budget across all of them in parallel. The
        previous implementation waited 2 s on each controller in
        sequence, which is what made closing the app take 2 s × N
        cameras. If a worker is still stuck in a SOAP call after the
        combined budget, its thread + Python wrapper are buried and
        the process exits.
        """
        controllers = list(self._controllers.values())
        for ctrl in controllers:
            try:
                ctrl.shutdown(block_ms=0)  # non-blocking quit
            except Exception:
                pass
        # Total budget for all controllers combined, not per controller.
        deadline_per = 300 // max(1, len(controllers)) if controllers else 0
        for ctrl in controllers:
            try:
                if deadline_per and ctrl._thread.wait(deadline_per):
                    continue
            except Exception:
                pass
            # Give up on cleanly waiting — the burial in shutdown()
            # already made this safe.
        for ctrl in controllers:
            try:
                ctrl.deleteLater()
            except Exception:
                pass
        self._controllers.clear()
