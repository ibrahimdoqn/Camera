"""libVLC-based RTSP worker with hardware-accelerated decode.

libVLC is the sole video decoder for the app. It's chosen because VLC
routes decode through the platform's hardware path automatically — DXVA2
and D3D11 on Windows, VAAPI on Linux, VideoToolbox on macOS — and its
RTSP client is significantly more reliable than the FFmpeg build that
ships inside ``opencv-python``.

Rather than embedding VLC's native output surface into a widget (which
would break the zoom / pan / overlay features), we install VLC's
``video_set_callbacks`` + ``video_set_format_callbacks`` pair to receive
decoded frames as CPU-side buffers. VLC still does the hardware decode
work; the readback to system memory is a tiny bandwidth cost by
comparison and it's what lets Qt paint the frame with the tile's
overlay chip and cursor-anchored zoom.

Signals ``frame_ready`` / ``status_changed`` / ``error`` / ``finished``
mirror the old ``StreamWorker`` contract exactly so :class:`CameraTile`
consumes both the same way.
"""
from __future__ import annotations

import ctypes
import shutil
import sys
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


# --- libVLC callback signatures --------------------------------------------
#
# python-vlc ships its own ``VideoFormatCb`` decorator but declares the
# ``chroma`` argument as ``c_char_p``, which ctypes converts into an
# immutable Python bytes on input — so there's no way to write the fourcc
# back. We redeclare the callback types with a ``POINTER(c_char)`` for
# chroma, which stays writeable, and use ``video_set_format_callbacks``
# directly with these.
_VLC_VideoFormatCb = ctypes.CFUNCTYPE(
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_char),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
    ctypes.POINTER(ctypes.c_uint),
)
_VLC_VideoCleanupCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
_VLC_VideoLockCb = ctypes.CFUNCTYPE(
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
)
_VLC_VideoUnlockCb = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
)
_VLC_VideoDisplayCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)


# --- HW-accel handling -----------------------------------------------------
#
# The Settings dialog exposes the same labels the old StreamWorker used, so
# saved configs migrate cleanly. Each label maps to the value libVLC wants
# for ``--avcodec-hw``. ``auto`` (aka ``None``) lets VLC pick, which is the
# recommended default — VLC's ``any`` path probes DXVA2 → D3D11 → software
# and settles on the first driver that succeeds.
_HW_ACCEL_TO_VLC: dict[str, Optional[str]] = {
    "auto":    None,
    "none":    "none",
    "d3d11va": "d3d11va",
    "dxva2":   "dxva2",
    "cuda":    "nvdec",   # VLC's option name for NVIDIA NVDEC
    "qsv":     "qsv",
}


ALL_HW_ACCEL_MODES: tuple[str, ...] = (
    "auto", "none", "d3d11va", "dxva2", "cuda", "qsv",
)


def _has_nvidia_gpu() -> bool:
    """Best-effort check for an NVIDIA GPU; gates the CUDA/NVDEC option."""
    if shutil.which("nvidia-smi") is not None:
        return True
    try:
        import cv2  # type: ignore
    except ImportError:
        return False
    try:
        return cv2.cuda.getCudaEnabledDeviceCount() > 0  # type: ignore[attr-defined]
    except (AttributeError, cv2.error):  # pragma: no cover - defensive
        return False


def detect_supported_hw_accels() -> list[str]:
    """Modes that plausibly work on this machine (populates the dropdown)."""
    modes: list[str] = ["auto", "none"]
    if sys.platform.startswith("win"):
        modes.extend(["d3d11va", "dxva2"])
    if _has_nvidia_gpu():
        modes.append("cuda")
    # Quick Sync is available on any recent Intel CPU with integrated
    # graphics; we can't detect that reliably at runtime without heavier
    # dependencies, so we always list it and let the runtime probe fall
    # back if the driver is missing.
    if sys.platform.startswith("win"):
        modes.append("qsv")
    return modes


def _vlc_hw_option(hw_accel: str) -> Optional[str]:
    return _HW_ACCEL_TO_VLC.get((hw_accel or "auto").lower())


# --- Watchdog timings ------------------------------------------------------
_HWACCEL_PROBE_S = 6.0   # first frame must arrive in this many seconds
_WATCHDOG_NO_FRAME_S = 8.0  # or a working stream is treated as dead


class VLCFrameWorker(QObject):
    """Read RTSP frames via libVLC + video callbacks.

    Public API and signal contract match the old ``StreamWorker`` so the
    tile keeps its paint / zoom / pan / overlay pipeline unchanged.
    """

    frame_ready = pyqtSignal(np.ndarray)      # BGRA frame (H, W, 4)
    status_changed = pyqtSignal(str)          # connecting | online | offline | error
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, url: str, target_fps: int = 20,
                 reconnect_delay: float = 3.0,
                 hw_accel: str = "auto") -> None:
        super().__init__()
        self._url = url
        self._target_fps = max(1, int(target_fps))
        self._reconnect_delay = reconnect_delay
        self._hw_accel = hw_accel or "auto"
        self._hw_accel_failed = False
        self._running = False

        # libVLC handles; owned by the run loop.
        self._instance = None
        self._player = None
        self._media = None

        # Frame buffer VLC decodes into. Allocated in ``format_cb``.
        self._buf = None
        self._buf_ptr = ctypes.c_void_p(0)
        self._width = 0
        self._height = 0

        # Emission throttling + watchdog state (touched from callback thread).
        self._last_emit = 0.0
        self._first_frame_seen = False
        self._connect_started = 0.0
        self._last_frame_ts = 0.0

        # Keep ctypes callback wrappers alive for the player's lifetime; if
        # they're GC'd libvlc holds dangling function pointers.
        self._cb_format = None
        self._cb_cleanup = None
        self._cb_lock = None
        self._cb_unlock = None
        self._cb_display = None

    # -- public control API ------------------------------------------------

    def update_url(self, url: str) -> None:
        self._url = url

    def update_target_fps(self, fps: int) -> None:
        self._target_fps = max(1, int(fps))

    def update_hw_accel(self, hw_accel: str) -> None:
        self._hw_accel = hw_accel or "auto"
        self._hw_accel_failed = False

    def stop(self) -> None:
        self._running = False

    # -- worker loop -------------------------------------------------------

    def _effective_hw_accel(self) -> str:
        if self._hw_accel_failed and self._hw_accel != "none":
            return "none"
        return self._hw_accel

    def run(self) -> None:
        self._running = True

        try:
            import vlc  # type: ignore  # noqa: F401
        except Exception as exc:  # pragma: no cover - VLC missing on the box
            self.error.emit(
                f"libVLC yüklenemedi: {exc}. "
                "https://www.videolan.org/vlc/ üzerinden VLC kurun."
            )
            self.status_changed.emit("error")
            self.finished.emit()
            return

        while self._running:
            hw_to_try = self._effective_hw_accel()
            self.status_changed.emit("connecting")

            if not self._start_player(hw_to_try):
                self._sleep_interruptible(self._reconnect_delay)
                continue

            # Block here until the stream fails, ends, or stop() is called.
            terminated_by_hw_failure = self._wait_until_terminated(hw_to_try)
            self._stop_player()

            if terminated_by_hw_failure:
                # Loop immediately with the CPU fallback; no offline blink.
                self._hw_accel_failed = True
                continue

            if self._running:
                self.status_changed.emit("offline")
                self._sleep_interruptible(self._reconnect_delay)

        self.status_changed.emit("offline")
        self.finished.emit()

    # -- libVLC lifecycle --------------------------------------------------

    def _start_player(self, hw_accel: str) -> bool:
        import vlc  # type: ignore

        # Keep the vlc.Instance itself lean — different libVLC point
        # releases accept different sets of global CLI options, and one
        # unknown option makes the whole Instance return None. Everything
        # stream-specific goes on the media object below, where it always
        # parses correctly.
        instance_args = [
            "--intf", "dummy",
            "--quiet",
            "--no-audio",         # audio is handled by the tile separately
            "--no-lua",
            "--no-osd",
            "--no-stats",
            "--no-video-title-show",
        ]

        try:
            self._instance = vlc.Instance(*instance_args)
            if self._instance is None:
                raise RuntimeError("vlc.Instance returned None")
            self._player = self._instance.media_player_new()
            self._media = self._instance.media_new(self._url)

            # Per-media options survive better across libVLC builds and
            # apply cleanly to just this stream. They cover:
            #   * ``rtsp-tcp``          — force TCP transport, no UDP loss
            #   * ``network-caching``   — target buffer (ms) for network
            #                              streams; 300 ms is the low-
            #                              latency VLC recommendation
            #   * ``live-caching``      — same, for live sources
            #   * ``clock-jitter=0``    — disables adaptive playback rate
            #   * ``no-audio``          — belt-and-braces, we don't want
            #                              audio from the video worker
            #   * ``avcodec-hw=<mode>`` — the hardware-decode path
            media_opts = [
                ":rtsp-tcp",
                ":network-caching=300",
                ":live-caching=300",
                ":clock-jitter=0",
                ":no-audio",
            ]
            vlc_hw = _vlc_hw_option(hw_accel)
            if vlc_hw is not None:
                media_opts.append(f":avcodec-hw={vlc_hw}")
            for opt in media_opts:
                self._media.add_option(opt)

            self._player.set_media(self._media)
        except Exception as exc:
            self.error.emit(f"VLC hazırlanamadı: {exc}")
            self._instance = None
            self._player = None
            self._media = None
            return False

        self._first_frame_seen = False
        self._last_emit = 0.0
        self._last_frame_ts = 0.0
        self._connect_started = time.monotonic()
        self._buf = None
        self._buf_ptr = ctypes.c_void_p(0)
        self._width = 0
        self._height = 0

        self._install_callbacks()

        try:
            self._player.play()
        except Exception as exc:
            self.error.emit(f"VLC oynatma başlatılamadı: {exc}")
            return False

        return True

    def _install_callbacks(self) -> None:
        """Wire up VLC's format + video callback plumbing."""

        # -- format negotiation: pick the chroma + allocate the frame buffer
        def format_cb(opaque, chroma, w_ptr, h_ptr, pitches, lines):
            try:
                w = int(w_ptr[0])
                h = int(h_ptr[0])
                if w <= 0 or h <= 0:
                    return 0
                # RV32 on little-endian x86 is packed BGRA in memory, which
                # is a perfect match for QImage.Format_ARGB32 on the paint
                # side. That saves a channel swap in the tile.
                fourcc = b"RV32"
                for i in range(4):
                    chroma[i] = fourcc[i:i + 1]
                pitches[0] = w * 4
                lines[0] = h
                size = w * h * 4
                # Allocate a page-aligned-ish buffer VLC will decode into.
                self._buf = (ctypes.c_ubyte * size)()
                self._buf_ptr = ctypes.c_void_p(ctypes.addressof(self._buf))
                self._width = w
                self._height = h
                return 1
            except Exception:
                return 0

        def cleanup_cb(opaque):
            self._buf = None
            self._buf_ptr = ctypes.c_void_p(0)
            self._width = 0
            self._height = 0

        # -- lock: tell VLC where to write the next frame
        def lock_cb(opaque, planes):
            planes[0] = self._buf_ptr
            return ctypes.c_void_p(0)

        # -- unlock: VLC has finished writing → snapshot to numpy + emit.
        # VLC does not decode the next frame until display_cb has returned,
        # so the buffer is stable for the duration of this callback.
        def unlock_cb(opaque, picture, planes):
            self._on_frame_ready()

        def display_cb(opaque, picture):
            # Nothing to do — the tile is what actually displays the frame.
            return

        self._cb_format = _VLC_VideoFormatCb(format_cb)
        self._cb_cleanup = _VLC_VideoCleanupCb(cleanup_cb)
        self._cb_lock = _VLC_VideoLockCb(lock_cb)
        self._cb_unlock = _VLC_VideoUnlockCb(unlock_cb)
        self._cb_display = _VLC_VideoDisplayCb(display_cb)

        # Install. ``video_set_format_callbacks`` MUST come before ``play()``
        # so VLC calls it during connection negotiation.
        self._player.video_set_format_callbacks(self._cb_format, self._cb_cleanup)
        self._player.video_set_callbacks(
            self._cb_lock, self._cb_unlock, self._cb_display, None
        )

    def _on_frame_ready(self) -> None:
        """Copy the current VLC buffer to a numpy array and emit."""
        buf = self._buf
        if buf is None or self._width == 0 or self._height == 0:
            return
        now = time.monotonic()
        self._last_frame_ts = now
        if not self._first_frame_seen:
            self._first_frame_seen = True
            # Announce online + first frame as soon as VLC delivers pixels.
            self.status_changed.emit("online")

        # Throttle to the tile's target FPS. Dropped frames are cheap
        # because we don't allocate anything until we're actually emitting.
        interval = 1.0 / max(1, self._target_fps)
        if now - self._last_emit < interval:
            return
        self._last_emit = now

        try:
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(
                (self._height, self._width, 4)
            ).copy()
        except Exception:
            return
        self.frame_ready.emit(frame)

    def _wait_until_terminated(self, hw_to_try: str) -> bool:
        """Block until the stream fails, ends, or ``stop()`` is called.

        Returns ``True`` if the failure was diagnosed as "the requested
        HW-accel path never produced a frame" — the caller uses that to
        re-enter the loop with the software fallback without a visible
        offline blink.
        """
        import vlc  # type: ignore

        hw_probe_armed = hw_to_try != "none"
        while self._running:
            time.sleep(0.15)
            try:
                state = self._player.get_state()
            except Exception:
                state = None
            now = time.monotonic()

            if state in (vlc.State.Error, vlc.State.Ended):
                if (hw_probe_armed
                        and not self._first_frame_seen
                        and now - self._connect_started > _HWACCEL_PROBE_S):
                    self.error.emit(
                        f"HW hızlandırma '{hw_to_try}' çalışmıyor — "
                        f"CPU dekodlamaya geçiliyor"
                    )
                    return True
                return False

            # HW-accel probe: no first frame within N seconds → treat as
            # broken and switch to CPU. The user will see connecting →
            # offline → connecting → online instead of a black tile.
            if (hw_probe_armed
                    and not self._first_frame_seen
                    and now - self._connect_started > _HWACCEL_PROBE_S):
                self.error.emit(
                    f"HW hızlandırma '{hw_to_try}' çalışmıyor — "
                    f"CPU dekodlamaya geçiliyor"
                )
                return True

            # Watchdog: previously-online stream stopped delivering frames.
            if (self._first_frame_seen
                    and now - self._last_frame_ts > _WATCHDOG_NO_FRAME_S):
                return False

        return False

    def _stop_player(self) -> None:
        """Tear down the libVLC objects.

        We deliberately do *not* call ``release()`` on the instance /
        player / media. libVLC's release path re-enters Python via cleanup
        callbacks and has been observed to crash when fired from a Qt
        event handler. Dropping our Python references lets Python's GC
        finalise the objects at a quiet moment; ``player.stop()`` closes
        the RTSP socket immediately so nothing keeps decoding.
        """
        player = self._player
        self._player = None
        self._media = None
        self._instance = None
        self._buf = None
        self._buf_ptr = ctypes.c_void_p(0)
        self._width = 0
        self._height = 0
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(0.1)
