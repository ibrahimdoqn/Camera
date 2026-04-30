"""Status-bar widget that polls CPU / GPU / network usage."""
from __future__ import annotations

import shutil
import subprocess
import time
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore


class _GpuProbe(QObject):
    """Polls nvidia-smi off the UI thread; emits utilization (%)."""

    sample = pyqtSignal(float)  # NaN when unavailable

    def __init__(self, interval: float = 1.5) -> None:
        super().__init__()
        self._interval = interval
        self._running = False
        self._available: Optional[bool] = None

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        while self._running:
            value = self._probe()
            self.sample.emit(value)
            end = time.monotonic() + self._interval
            while self._running and time.monotonic() < end:
                time.sleep(0.1)

    def _probe(self) -> float:
        if self._available is False:
            return float("nan")
        if shutil.which("nvidia-smi") is None:
            self._available = False
            return float("nan")
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL,
                timeout=2.0,
            )
            self._available = True
            return float(out.decode().strip().splitlines()[0])
        except Exception:
            self._available = False
            return float("nan")


class ResourceMonitor(QWidget):
    """Compact CPU / GPU / network indicator for the status bar."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cpu_label = QLabel("CPU —")
        self._gpu_label = QLabel("GPU —")
        self._net_label = QLabel("Ağ —")
        for lbl in (self._cpu_label, self._gpu_label, self._net_label):
            lbl.setObjectName("ResourceLabel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        layout.addWidget(self._cpu_label)
        layout.addWidget(self._gpu_label)
        layout.addWidget(self._net_label)

        self._last_net = self._net_counters()
        self._last_net_t = time.monotonic()

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._refresh_cpu_net)

        self._gpu_thread: Optional[QThread] = None
        self._gpu_probe: Optional[_GpuProbe] = None

        if psutil is not None:
            # Prime the cpu_percent counter so the first reading isn't 0.
            psutil.cpu_percent(interval=None)
            self._timer.start()
            self._start_gpu_probe()
        else:
            self._cpu_label.setText("CPU n/a")
            self._gpu_label.setText("GPU n/a")
            self._net_label.setText("Ağ n/a")

    # -- helpers --

    def _net_counters(self) -> tuple[int, int]:
        if psutil is None:
            return (0, 0)
        c = psutil.net_io_counters()
        return (c.bytes_sent, c.bytes_recv)

    def _start_gpu_probe(self) -> None:
        thread = QThread(self)
        probe = _GpuProbe()
        probe.moveToThread(thread)
        thread.started.connect(probe.run)
        probe.sample.connect(self._on_gpu_sample)
        thread.start()
        self._gpu_thread = thread
        self._gpu_probe = probe

    def _on_gpu_sample(self, value: float) -> None:
        if value != value:  # NaN check
            self._gpu_label.setText("GPU n/a")
        else:
            self._gpu_label.setText(f"GPU {value:.0f}%")

    def _refresh_cpu_net(self) -> None:
        if psutil is None:
            return
        cpu = psutil.cpu_percent(interval=None)
        self._cpu_label.setText(f"CPU {cpu:.0f}%")

        sent, recv = self._net_counters()
        now = time.monotonic()
        dt = max(1e-3, now - self._last_net_t)
        rate_bps = ((sent - self._last_net[0]) + (recv - self._last_net[1])) / dt
        self._last_net = (sent, recv)
        self._last_net_t = now
        self._net_label.setText(f"Ağ {self._format_rate(rate_bps)}")

    @staticmethod
    def _format_rate(bytes_per_sec: float) -> str:
        bits = max(0.0, bytes_per_sec) * 8.0
        for unit in ("bps", "Kbps", "Mbps", "Gbps"):
            if bits < 1024:
                return f"{bits:.0f} {unit}" if unit == "bps" else f"{bits:.1f} {unit}"
            bits /= 1024
        return f"{bits:.1f} Tbps"

    def shutdown(self) -> None:
        self._timer.stop()
        if self._gpu_probe is not None:
            self._gpu_probe.stop()
        if self._gpu_thread is not None:
            self._gpu_thread.quit()
            self._gpu_thread.wait(1500)
