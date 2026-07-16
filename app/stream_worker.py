"""Background RTSP capture worker using OpenCV's FFmpeg backend.

GPU/hardware decoding is configured per-capture via ``CAP_PROP_HW_ACCELERATION``
and per-process via the ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` env var. Both knobs
are honoured by the FFmpeg backend bundled with ``opencv-python``.

The worker also implements a small watchdog: if no successful frame arrives
for ``WATCHDOG_TIMEOUT`` seconds (or no frame at all on a fresh connection
with hardware acceleration), the capture is forcibly closed so the outer
loop can reconnect. This is what makes the "online" badge flip back to
"offline" reliably when a camera silently drops off the network — without
it, FFmpeg can sit on a half-open TCP socket forever and the green dot
keeps blinking.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


# Avoid flashing a console window when running as a windowed Windows .exe.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# Map a user-friendly hw-accel name (the same labels exposed in Settings) to
# the OpenCV ``VIDEO_ACCELERATION_*`` constant and the ``hwaccel`` value we
# pass to FFmpeg via the env var. ``cuda`` is the right choice for NVIDIA
# cards (RTX 30/40 series) — FFmpeg routes it through NVDEC.
_HW_ACCEL_MAP: dict[str, tuple[int, str]] = {
    # name : (cv2 hw_acceleration enum, ffmpeg hwaccel name)
    "auto":    (1, ""),         # VIDEO_ACCELERATION_ANY — pick best at runtime
    "none":    (0, ""),         # VIDEO_ACCELERATION_NONE — pure CPU
    "cuda":    (1, "cuda"),     # NVDEC via FFmpeg (NVIDIA GPUs)
    "d3d11va": (2, "d3d11va"),  # VIDEO_ACCELERATION_D3D11 (Windows DXVA 2.0)
    "dxva2":   (1, "dxva2"),    # FFmpeg-side DXVA2; OpenCV maps to ANY
    "qsv":     (1, "qsv"),      # Intel Quick Sync (integrated GPUs)
}


# A sensible default order for the dropdown when every mode is supported.
ALL_HW_ACCEL_MODES: tuple[str, ...] = ("auto", "none", "d3d11va", "dxva2", "cuda", "qsv")


# ---- Playback backend registry --------------------------------------------
# ``opencv`` is always available (opencv-python is a hard requirement).
# ``ffmpeg`` requires ``ffmpeg`` + ``ffprobe`` on PATH.
# ``vlc``    requires the ``python-vlc`` module *and* a libvlc shared library
#            reachable at import time.
ALL_PLAYBACK_BACKENDS: tuple[str, ...] = ("opencv", "ffmpeg", "vlc")


def _has_ffmpeg_binary() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _has_vlc_module() -> bool:
    try:
        import vlc  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def detect_supported_backends() -> list[str]:
    """Return which playback engines can actually run on this machine.

    ``opencv`` is always present. ``ffmpeg`` needs the system binaries.
    ``vlc`` needs python-vlc + a working libvlc.
    """
    backends: list[str] = ["opencv"]
    if _has_ffmpeg_binary():
        backends.append("ffmpeg")
    if _has_vlc_module():
        backends.append("vlc")
    return backends


def _resolve_hw_accel(name: str) -> tuple[int, str]:
    """Look up the OpenCV / FFmpeg hwaccel pair for ``name`` (case-insensitive)."""
    return _HW_ACCEL_MAP.get((name or "auto").lower(), _HW_ACCEL_MAP["auto"])


def _has_nvidia_gpu() -> bool:
    """Best-effort check for an NVIDIA GPU; gates the CUDA/NVDEC option."""
    if shutil.which("nvidia-smi") is not None:
        return True
    try:
        return cv2.cuda.getCudaEnabledDeviceCount() > 0  # type: ignore[attr-defined]
    except (AttributeError, cv2.error):
        return False


def detect_supported_hw_accels() -> list[str]:
    """Return the list of HW-accel modes that can plausibly work on this
    system, used to populate the Settings dropdown.

    The check is conservative — we filter out platforms where the underlying
    FFmpeg backend cannot use the mode at all (e.g. ``d3d11va`` outside
    Windows, ``cuda`` without an NVIDIA GPU). Whether a *given* RTSP stream
    actually plays with the chosen mode also depends on the camera's codec
    and the system's drivers; for that reason :class:`StreamWorker` will
    silently fall back to ``"none"`` at runtime if a non-CPU mode produces
    no frames within a few seconds. Together, these two layers prevent the
    user from sitting on a black tile because their GPU does not support
    ``dxva2`` / ``d3d11va`` / ``cuda``.
    """
    modes: list[str] = ["auto", "none"]
    if sys.platform.startswith("win"):
        # DirectX paths are Windows-only. Both are exposed because some
        # GPUs/drivers prefer one over the other.
        modes.extend(["d3d11va", "dxva2"])
    if _has_nvidia_gpu():
        modes.append("cuda")
    return modes


# Default RTSP options applied to every capture. We keep these on the worker
# rather than baking them into a single env var at process start so we can
# layer the per-stream hwaccel choice on top without losing transport tweaks.
#
# Why every option matters:
# * ``rtsp_transport;tcp`` — avoids UDP packet loss on noisy Wi-Fi.
# * ``stimeout`` / ``timeout`` — socket I/O timeout. ``stimeout`` is the
#   classic name; newer FFmpeg builds prefer ``timeout`` for RTSP. We pass
#   both so cap.read() returns within ~5 s when the camera goes offline,
#   instead of blocking forever.
# * ``rw_timeout`` — fallback I/O timeout honoured by some FFmpeg builds
#   that ignore the protocol-specific knobs.
# * ``max_delay`` / ``buffer_size`` — keep latency low.
_BASE_FFMPEG_OPTS = (
    "rtsp_transport;tcp"
    "|stimeout;5000000"
    "|timeout;5000000"
    "|rw_timeout;5000000"
    "|max_delay;500000"
    "|buffer_size;1024000"
)


def _ffmpeg_options_for(hw_accel: str) -> str:
    """Build the ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` payload for ``hw_accel``."""
    _, ffmpeg_name = _resolve_hw_accel(hw_accel)
    if not ffmpeg_name:
        return _BASE_FFMPEG_OPTS
    # ``hwaccel`` tells FFmpeg to attempt hardware decoding for this capture.
    # ``hwaccel_output_format`` keeps the surfaces in GPU memory until the
    # final RGB conversion, which is what actually relieves CPU pressure on
    # H.264/H.265 RTSP streams.
    extras = f"hwaccel;{ffmpeg_name}|hwaccel_output_format;{ffmpeg_name}"
    return f"{_BASE_FFMPEG_OPTS}|{extras}"


# Watchdog thresholds. They're deliberately conservative so a brief
# network hiccup doesn't tear down a working stream.
WATCHDOG_NO_FRAME_S = 8.0     # online → offline if no fresh frame for this long
HWACCEL_PROBE_S = 6.0         # GPU mode considered broken if no first frame
                              # arrives within this many seconds of opening
                              # the capture
MAX_CONSECUTIVE_FAILURES = 30


class StreamWorker(QObject):
    """Reads frames from an RTSP URL and emits them as numpy arrays (BGR)."""

    frame_ready = pyqtSignal(np.ndarray)
    status_changed = pyqtSignal(str)  # "connecting" | "online" | "offline" | "error"
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, url: str, target_fps: int = 20,
                 reconnect_delay: float = 3.0,
                 hw_accel: str = "auto") -> None:
        super().__init__()
        self._url = url
        self._target_fps = max(1, target_fps)
        self._reconnect_delay = reconnect_delay
        self._hw_accel = hw_accel or "auto"
        # Set to True at runtime if the chosen hwaccel produces no frames.
        # Reset on every external change to ``_hw_accel`` so the user can
        # opt back in to GPU decoding from Settings without restarting the
        # app.
        self._hw_accel_failed = False
        self._running = False

    def update_url(self, url: str) -> None:
        self._url = url

    def update_target_fps(self, fps: int) -> None:
        self._target_fps = max(1, int(fps))

    def update_hw_accel(self, hw_accel: str) -> None:
        self._hw_accel = hw_accel or "auto"
        # User explicitly picked a mode; clear the broken-mode latch so we
        # actually try it again on the next reconnect.
        self._hw_accel_failed = False

    def stop(self) -> None:
        self._running = False

    def _effective_hw_accel(self) -> str:
        """Mode actually used for the next capture attempt. Falls back to
        ``"none"`` after the runtime probe decided the configured mode is
        broken on this machine, so the user always sees video."""
        if self._hw_accel_failed and self._hw_accel != "none":
            return "none"
        return self._hw_accel

    def _open_capture(self, hw_accel: str) -> Optional[cv2.VideoCapture]:
        """Open the RTSP stream with the configured hardware acceleration.

        FFmpeg reads ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` once, when the capture
        is constructed, so we set it just before calling ``VideoCapture``. The
        OpenCV-level ``CAP_PROP_HW_ACCELERATION`` property is the second lever
        — together they give us the best chance of routing the decode through
        the GPU regardless of which path the bundled FFmpeg supports.
        """
        accel_enum, _ = _resolve_hw_accel(hw_accel)
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _ffmpeg_options_for(hw_accel)
        try:
            params = [
                cv2.CAP_PROP_HW_ACCELERATION, accel_enum,
                cv2.CAP_PROP_HW_DEVICE, 0,
            ]
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG, params)
        except (TypeError, AttributeError):
            # Older OpenCV builds don't accept the params overload — fall
            # back to the 2-arg form. The env-var hwaccel hint above still
            # applies, so we don't lose GPU decoding entirely.
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        return cap

    def run(self) -> None:
        self._running = True

        while self._running:
            hw_to_try = self._effective_hw_accel()
            self.status_changed.emit("connecting")
            cap = self._open_capture(hw_to_try)

            if cap is None or not cap.isOpened():
                self.status_changed.emit("offline")
                self.error.emit("Bağlantı kurulamadı")
                if cap is not None:
                    cap.release()
                self._sleep_interruptible(self._reconnect_delay)
                continue

            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except cv2.error:
                pass

            self.status_changed.emit("online")
            last_emit = 0.0
            connection_start = time.monotonic()
            last_success = connection_start
            consecutive_failures = 0
            first_frame_received = False
            hw_fallback_armed = (hw_to_try != "none")

            while self._running:
                ok, frame = cap.read()
                now = time.monotonic()

                if not ok or frame is None:
                    consecutive_failures += 1

                    # Hardware-accel runtime probe: if a non-CPU mode has
                    # not produced even one frame within the probe window,
                    # latch the failure flag and reconnect with "none". The
                    # user will see a brief "connecting" → "online" cycle
                    # but then get continuous video instead of a black tile.
                    if (hw_fallback_armed
                            and not first_frame_received
                            and now - connection_start > HWACCEL_PROBE_S):
                        self._hw_accel_failed = True
                        self.error.emit(
                            f"HW hızlandırma '{hw_to_try}' çalışmıyor — "
                            f"CPU dekodlamaya geçiliyor"
                        )
                        break

                    # Watchdog: a previously-online stream that hasn't
                    # delivered a fresh frame for a while is treated as
                    # offline so the outer loop reconnects.
                    if first_frame_received and now - last_success > WATCHDOG_NO_FRAME_S:
                        break

                    # Fast-path: a flurry of bad reads in a row also
                    # qualifies as a dead capture (typical of FFmpeg
                    # returning ``False`` immediately after the camera
                    # closes the socket).
                    if consecutive_failures > MAX_CONSECUTIVE_FAILURES:
                        break

                    time.sleep(0.05)
                    continue

                consecutive_failures = 0
                last_success = now
                first_frame_received = True

                # Re-read each iteration so a settings change applies immediately.
                interval = 1.0 / max(1, self._target_fps)
                if now - last_emit >= interval:
                    last_emit = now
                    self.frame_ready.emit(frame)

            cap.release()
            if self._running:
                self.status_changed.emit("offline")
                self._sleep_interruptible(self._reconnect_delay)

        self.status_changed.emit("offline")
        self.finished.emit()

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(0.1)


# ---- FFmpeg subprocess backend --------------------------------------------
#
# The bundled OpenCV FFmpeg cannot always negotiate the requested hardware
# path — the user's report ("only d3d11va works") is a direct symptom.
# Shelling out to the system's ``ffmpeg`` gives us direct access to the
# native ``-hwaccel`` flag, which is the codec-team-blessed way to route a
# decode through the GPU. We probe dimensions with ``ffprobe`` up front so
# the raw-video pipe protocol is unambiguous, then read tightly packed BGR24
# frames off stdout.


def _probe_stream_dims(url: str, timeout: float = 8.0) -> Optional[tuple[int, int]]:
    """Return (width, height) for the primary video track, or ``None``."""
    probe = shutil.which("ffprobe")
    if probe is None:
        return None
    cmd = [
        probe,
        "-v", "error",
        "-rtsp_transport", "tcp",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        url,
    ]
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        ).decode("ascii", errors="ignore").strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if not out or "x" not in out:
        return None
    try:
        w_str, h_str = out.splitlines()[0].split("x")[:2]
        w, h = int(w_str), int(h_str)
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return w, h


def _ffmpeg_command(url: str, hw_accel: str) -> list[str]:
    """Build the ffmpeg CLI for a raw-video BGR24 pipe."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd: list[str] = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-rtsp_transport", "tcp",
        "-stimeout", "5000000",
    ]
    _, ffmpeg_name = _resolve_hw_accel(hw_accel)
    if ffmpeg_name:
        # ``-hwaccel`` decodes on the GPU. We deliberately omit
        # ``-hwaccel_output_format`` so ffmpeg transfers the frames back to
        # system memory as normal software surfaces — the pipe below expects
        # BGR24 in RAM. The GPU still absorbs the codec work, which is where
        # the real CPU savings come from.
        cmd += ["-hwaccel", ffmpeg_name]
    cmd += [
        "-i", url,
        "-an",
        "-sn",
        "-vf", "format=bgr24",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-",
    ]
    return cmd


def _read_exact(pipe, n: int) -> Optional[bytes]:
    """Read exactly ``n`` bytes from ``pipe`` or return ``None`` on EOF."""
    buf = bytearray()
    remaining = n
    while remaining > 0:
        chunk = pipe.read(remaining)
        if not chunk:
            return None
        buf.extend(chunk)
        remaining -= len(chunk)
    return bytes(buf)


class FFmpegSubprocessWorker(QObject):
    """Subprocess-based worker that uses the system ``ffmpeg`` binary.

    Behaviour and signals mirror :class:`StreamWorker` so the two backends
    are hot-swappable inside :class:`~app.camera_tile.CameraTile`.
    """

    frame_ready = pyqtSignal(np.ndarray)
    status_changed = pyqtSignal(str)
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

    def update_url(self, url: str) -> None:
        self._url = url

    def update_target_fps(self, fps: int) -> None:
        self._target_fps = max(1, int(fps))

    def update_hw_accel(self, hw_accel: str) -> None:
        self._hw_accel = hw_accel or "auto"
        self._hw_accel_failed = False

    def stop(self) -> None:
        self._running = False

    def _effective_hw_accel(self) -> str:
        if self._hw_accel_failed and self._hw_accel != "none":
            return "none"
        return self._hw_accel

    def _spawn(self, hw_accel: str, width: int, height: int) -> Optional[subprocess.Popen]:
        cmd = _ffmpeg_command(self._url, hw_accel)
        try:
            return subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
                bufsize=width * height * 3 * 2,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.error.emit(f"ffmpeg başlatılamadı: {exc}")
            return None

    def run(self) -> None:
        self._running = True

        while self._running:
            hw_to_try = self._effective_hw_accel()
            self.status_changed.emit("connecting")

            dims = _probe_stream_dims(self._url)
            if dims is None:
                self.error.emit("Akış boyutları alınamadı")
                self.status_changed.emit("offline")
                self._sleep_interruptible(self._reconnect_delay)
                continue
            width, height = dims
            frame_bytes = width * height * 3

            proc = self._spawn(hw_to_try, width, height)
            if proc is None or proc.stdout is None:
                self.status_changed.emit("offline")
                self._sleep_interruptible(self._reconnect_delay)
                continue

            self.status_changed.emit("online")
            connection_start = time.monotonic()
            last_emit = 0.0
            first_frame_received = False
            hw_fallback_armed = (hw_to_try != "none")

            try:
                while self._running:
                    payload = _read_exact(proc.stdout, frame_bytes)
                    now = time.monotonic()

                    if payload is None:
                        # EOF or read error. Distinguish "hw accel never
                        # produced a frame" from "stream ended cleanly".
                        if (hw_fallback_armed
                                and not first_frame_received
                                and now - connection_start > HWACCEL_PROBE_S):
                            self._hw_accel_failed = True
                            self.error.emit(
                                f"HW hızlandırma '{hw_to_try}' çalışmıyor — "
                                f"CPU dekodlamaya geçiliyor"
                            )
                        break

                    first_frame_received = True
                    frame = np.frombuffer(payload, dtype=np.uint8).reshape(
                        (height, width, 3)
                    )

                    interval = 1.0 / max(1, self._target_fps)
                    if now - last_emit >= interval:
                        last_emit = now
                        # Copy so downstream code isn't reading from a numpy
                        # view of a buffer we're about to overwrite.
                        self.frame_ready.emit(frame.copy())
            finally:
                self._terminate(proc)

            if self._running:
                self.status_changed.emit("offline")
                self._sleep_interruptible(self._reconnect_delay)

        self.status_changed.emit("offline")
        self.finished.emit()

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        try:
            proc.terminate()
        except (OSError, ProcessLookupError):
            return
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except (OSError, ProcessLookupError):
                pass
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(0.1)
