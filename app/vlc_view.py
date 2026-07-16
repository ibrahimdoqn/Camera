"""libVLC-based RTSP worker.

libVLC is the sole video decoder for the app. It's chosen because VLC:

* Has a robust RTSP client.
* **Enables hardware-accelerated decode automatically** — its default
  ``avcodec-hw`` value is ``any``, which probes every hardware driver
  the platform exposes (DXVA2 / D3D11 on Windows, VAAPI on Linux,
  VideoToolbox on macOS, NVDEC on NVIDIA GPUs, Quick Sync on Intel
  iGPUs) and settles on the first driver that succeeds. If nothing
  works, VLC transparently falls back to software decoding. There is
  no user setting to configure — that was the whole point of moving
  off OpenCV / FFmpeg.

Rather than embedding VLC's native output surface into a widget (which
would break the zoom / pan / overlay features), we install VLC's
``video_set_callbacks`` + ``video_set_format_callbacks`` pair to receive
decoded frames as CPU-side buffers. VLC still does the hardware decode
work; the readback to system memory is a tiny bandwidth cost by
comparison and it's what lets Qt paint the frame with the tile's
overlay chip and cursor-anchored zoom.

Signals ``frame_ready`` / ``status_changed`` / ``error`` / ``finished``
mirror the old ``StreamWorker`` contract exactly so :class:`CameraTile`
consumes them the same way.
"""
from __future__ import annotations

import ctypes
import os
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from .logger import get_logger


_log = get_logger("vlc")


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


# libVLC log callback: ``void log_cb(void *data, int level,
# const libvlc_log_t *ctx, const char *fmt, va_list args)``. The
# va_list is opaque to us — we can't format the placeholders in Python
# without calling vsnprintf via ctypes (ABI-specific), so we log the
# raw format template. It's still enough to tell "avcodec: using %s
# hardware decoder" from "avcodec: no hardware acceleration".
_VLC_LogCb = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,  # data
    ctypes.c_int,     # level (0=DEBUG, 2=NOTICE, 3=WARNING, 4=ERROR)
    ctypes.c_void_p,  # ctx (libvlc_log_t*)
    ctypes.c_char_p,  # fmt
    ctypes.c_void_p,  # args (va_list, opaque)
)


# Map libVLC's log levels onto Python's logging levels. libvlc uses:
#   0 = DEBUG, 2 = NOTICE, 3 = WARNING, 4 = ERROR. (There's no 1.)
# We deliberately clamp *everything* to DEBUG so the messages only
# appear when the user explicitly enables DEBUG-level file logging via
# Settings — otherwise the raw format strings (which we can't resolve
# because va_list is opaque to ctypes) would be pure noise in stderr.
# The important diagnostic messages (VLC's "Using D3D11VA for hardware
# decoding" NOTICE for instance) still show up when DEBUG logging is
# on, which is exactly when the user is investigating a problem.
import logging as _stdlib_logging  # noqa: E402
_LIBVLC_LEVEL_MAP = {
    0: _stdlib_logging.DEBUG,
    2: _stdlib_logging.DEBUG,
    3: _stdlib_logging.DEBUG,
    4: _stdlib_logging.DEBUG,
}


# Environment override to force libVLC's HW-accel path. Useful when
# something's clearly wrong (e.g. NVDEC gauge stays at 0 and the log
# says "avcodec: no hardware acceleration"). Values match libVLC's
# ``avcodec-hw`` option: ``any`` (default), ``none``, ``nvdec``,
# ``d3d11va``, ``dxva2``, ``vaapi``, …
_HW_ACCEL_OVERRIDE = os.environ.get("TAPOVIEWER_VLC_HW", "").strip() or None


# --- Watchdog timings ------------------------------------------------------
# If a fresh connection produces no frame for this long, tear it down and
# reconnect. Same threshold as the previous StreamWorker so behaviour is
# unchanged.
_FIRST_FRAME_TIMEOUT_S = 8.0
_ONGOING_FRAME_TIMEOUT_S = 8.0


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
                 reconnect_delay: float = 3.0) -> None:
        super().__init__()
        self._url = url
        self._target_fps = max(1, int(target_fps))
        self._reconnect_delay = reconnect_delay
        self._running = False
        # When True, the tile is off-screen (usually because another tile
        # was maximized). We keep the libVLC pipeline running so audio,
        # the reconnect loop and the watchdog stay live, but skip the
        # numpy copy + Qt signal marshaling for each decoded frame —
        # painting into a QPixmap that nobody looks at is pure waste.
        self._paused = False

        # libVLC handles; owned by the run loop.
        self._instance = None
        self._player = None
        self._media = None

        # Frame buffer VLC decodes into. Allocated in ``format_cb``.
        # ``_buf_addr`` is the integer address ctypes will hand to
        # libvlc — using a plain int (not a c_void_p wrapper) avoids
        # "cannot be converted to pointer" errors on Windows.
        self._buf = None
        self._buf_addr: int = 0
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
        self._cb_log = None

    # -- public control API ------------------------------------------------

    def update_url(self, url: str) -> None:
        self._url = url

    def update_target_fps(self, fps: int) -> None:
        self._target_fps = max(1, int(fps))

    def set_paused(self, paused: bool) -> None:
        """Toggle the frame-emit path without stopping libVLC.

        A paused worker still consumes RTSP data and drives its watchdog
        (so the sidebar status dot stays accurate and audio keeps
        playing), but doesn't hand decoded frames up to the UI. Useful
        when another tile has been maximized and this one's paint output
        would just be thrown away.
        """
        was_paused = self._paused
        self._paused = bool(paused)
        if was_paused and not paused:
            # Fire the next frame straight away instead of waiting for
            # the throttle interval to elapse.
            self._last_emit = 0.0

    def stop(self) -> None:
        self._running = False

    # -- worker loop -------------------------------------------------------

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
            self.status_changed.emit("connecting")

            if not self._start_player():
                self._sleep_interruptible(self._reconnect_delay)
                continue

            # Block here until the stream fails, ends, or stop() is called.
            self._wait_until_terminated()
            self._stop_player()

            if self._running:
                self.status_changed.emit("offline")
                self._sleep_interruptible(self._reconnect_delay)

        self.status_changed.emit("offline")
        self.finished.emit()

    # -- libVLC lifecycle --------------------------------------------------

    def _start_player(self) -> bool:
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

            # Route libVLC's log stream through a filter callback:
            #   * Drop the "deprecated pixel format" / "swscaler" spam
            #     that fires once per decoded frame. (--quiet at the
            #     instance level does not gate libavcodec's own av_log
            #     stream, so we need a callback to silence it.)
            #   * Forward everything else to Python's logger at the
            #     matching level. When the user turns file logging on in
            #     Settings, they'll see exactly which decoder VLC picked
            #     — e.g. "avcodec: Using D3D11VA for hardware decoding"
            #     or "avcodec: no hardware acceleration available" —
            #     which is the definitive answer to "is the GPU actually
            #     being used?".
            self._install_log_callback()

            self._player = self._instance.media_player_new()
            self._media = self._instance.media_new(self._url)

            # Per-media options survive better across libVLC builds and
            # apply cleanly to just this stream. Notably we do NOT pass
            # ``:avcodec-hw=<mode>`` — VLC's default is ``any``, which
            # picks the best available hardware decoder on its own (DXVA2
            # / D3D11 / NVDEC / Quick Sync / VAAPI / …) and cleanly falls
            # back to software if none of them work.
            #
            # Multi-core hooks:
            #   * ``avcodec-threads=0``   — libavcodec's own thread pool
            #     auto-sizes to the CPU core count; setting it explicitly
            #     documents the intent and forces the sensible default on
            #     older VLC builds where the default was 1.
            #   * ``avcodec-fast``        — enables non-strict decode
            #     shortcuts (skip loop-filter details, faster IDCT paths).
            #     Safe for live video where we favour throughput over
            #     bitstream-perfect reconstruction.
            #   * ``avcodec-hurry-up``    — decoder skips B-frames when it
            #     can't keep up in real time, preventing the pipeline from
            #     falling behind and eating CPU catching up.
            media_opts = [
                ":rtsp-tcp",             # avoid UDP loss on noisy Wi-Fi
                ":network-caching=300",  # 300 ms is VLC's low-latency default
                ":live-caching=300",
                ":clock-jitter=0",
                ":no-audio",             # belt-and-braces
                ":avcodec-threads=0",    # auto = one thread per CPU core
                ":avcodec-fast",
                ":avcodec-hurry-up",
                # ``any`` is libVLC's default but we spell it out so it's
                # obvious we're asking for hardware decode. The value can
                # be overridden at runtime by setting the
                # ``TAPOVIEWER_VLC_HW`` env var to e.g. ``nvdec`` (force
                # NVIDIA) or ``d3d11va`` (force Windows DirectX 11).
                f":avcodec-hw={_HW_ACCEL_OVERRIDE or 'any'}",
            ]
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
        self._buf_addr = 0
        self._width = 0
        self._height = 0

        self._install_callbacks()

        try:
            self._player.play()
        except Exception as exc:
            self.error.emit(f"VLC oynatma başlatılamadı: {exc}")
            return False

        return True

    def _install_log_callback(self) -> None:
        """Filter libVLC's log stream into Python's logger.

        This callback fires on VLC threads (potentially many concurrently
        across cameras). Python's logging module is thread-safe so we
        can log directly without extra synchronisation. We swallow the
        one high-volume message ("deprecated pixel format used, make
        sure you did set range correctly") because it's a benign
        libavcodec swscale advisory that would otherwise fill the log
        with a line every frame.
        """
        def log_cb(data, level, ctx, fmt, args):
            if not fmt:
                return
            try:
                msg = fmt.decode("utf-8", errors="replace") if isinstance(fmt, bytes) else str(fmt)
            except Exception:
                return
            low = msg.lower()
            if "deprecated pixel format" in low or "swscaler" in low:
                return
            py_level = _LIBVLC_LEVEL_MAP.get(int(level), _stdlib_logging.DEBUG)
            # Format string may contain %s / %d placeholders that we
            # can't resolve without vsnprintf, but even the template is
            # diagnostic — "avcodec: Using %s for hardware decoding"
            # already tells us HW-accel was attempted.
            _log.log(py_level, "%s", msg)

        self._cb_log = _VLC_LogCb(log_cb)
        try:
            self._instance.log_set(self._cb_log, None)
        except Exception:
            # Older libvlc builds may reject our callback signature.
            # Fall back to log_unset so we don't spam the console.
            try:
                self._instance.log_unset()
            except Exception:
                pass

    def _install_callbacks(self) -> None:
        """Wire up VLC's format + video callback plumbing."""

        # -- format negotiation: pick the chroma + allocate the frame buffer
        def format_cb(opaque, chroma, w_ptr, h_ptr, pitches, lines):
            try:
                w = int(w_ptr[0])
                h = int(h_ptr[0])
                if w <= 0 or h <= 0:
                    return 0
                # RV32 on little-endian x86 is packed BGRA in memory,
                # which is a perfect match for QImage.Format_ARGB32 on
                # the paint side. That saves a channel swap in the tile.
                # memmove is the cleanest way to write into the char*
                # buffer libvlc handed us.
                ctypes.memmove(chroma, b"RV32", 4)
                pitches[0] = w * 4
                lines[0] = h
                size = w * h * 4
                # Allocate the buffer VLC will decode into. Store the
                # raw integer address alongside — libvlc's lock callback
                # expects a plain integer pointer, not a ctypes wrapper.
                self._buf = (ctypes.c_ubyte * size)()
                self._buf_addr = ctypes.addressof(self._buf)
                self._width = w
                self._height = h
                return 1
            except Exception:
                return 0

        def cleanup_cb(opaque):
            self._buf = None
            self._buf_addr = 0
            self._width = 0
            self._height = 0

        # -- lock: tell VLC where to write the next frame.
        # The callback's declared return type is c_void_p; ctypes requires
        # either an int or None, so we return the buffer address as an int
        # (not a c_void_p wrapper) and let ctypes cast it for us.
        def lock_cb(opaque, planes):
            addr = self._buf_addr
            planes[0] = addr
            return addr

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

        # If the tile is off-screen there is no point copying the frame
        # or waking up the UI thread. The watchdog above has already
        # noted the frame arrived, which is all the state the reconnect
        # loop cares about.
        if self._paused:
            return

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

    def _wait_until_terminated(self) -> None:
        """Block until the stream fails, ends, or ``stop()`` is called."""
        import vlc  # type: ignore

        while self._running:
            time.sleep(0.15)
            try:
                state = self._player.get_state()
            except Exception:
                state = None
            now = time.monotonic()

            if state in (vlc.State.Error, vlc.State.Ended):
                return

            # First-frame watchdog: no video ever arrived → give up and
            # let the outer loop reconnect.
            if (not self._first_frame_seen
                    and now - self._connect_started > _FIRST_FRAME_TIMEOUT_S):
                return

            # Ongoing watchdog: previously-online stream stopped delivering
            # frames.
            if (self._first_frame_seen
                    and now - self._last_frame_ts > _ONGOING_FRAME_TIMEOUT_S):
                return

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
        self._buf_addr = 0
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
