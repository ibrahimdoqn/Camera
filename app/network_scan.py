"""MAC-address based local-network IP rediscovery.

When a camera's configured host stops answering (a typical DHCP rotation),
we walk the local subnet looking for the camera's recorded MAC address.
This is intentionally conservative:

* The lookup is only attempted if the camera has a known MAC (captured the
  first time it was reachable on its configured host).
* It only runs for the LAN that the user's machine is currently on — it
  does not try to enumerate remote networks.
* The probe is a non-intrusive ARP cache read after a quick ICMP / TCP
  sweep. We never modify any system state.

Functions here run on a worker :class:`QThread` so the UI thread is never
blocked during the scan.
"""
from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from .logger import get_logger


_log = get_logger("network_scan")


_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")


def _normalize_mac(value: str) -> str:
    if not value:
        return ""
    return value.lower().replace("-", ":").strip()


def _local_ipv4_subnets() -> list[ipaddress.IPv4Network]:
    """Best-effort enumeration of the local IPv4 /24-or-smaller subnets."""
    networks: list[ipaddress.IPv4Network] = []
    try:
        # Prefer the IP we'd use to reach the public internet — it usually
        # corresponds to the user's primary LAN interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
        # Treat as a /24 (the most common home / SMB layout).
        net = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        networks.append(net)
    except OSError:
        pass
    return networks


def _arp_table() -> dict[str, str]:
    """Return a mapping of ``ip -> mac`` from the OS ARP cache."""
    result: dict[str, str] = {}
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                ["arp", "-a"],
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            ).decode("utf-8", errors="ignore")
        else:
            out = subprocess.check_output(
                ["arp", "-an"],
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            ).decode("utf-8", errors="ignore")
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return result

    for line in out.splitlines():
        match = _MAC_RE.search(line)
        if not match:
            continue
        mac = _normalize_mac(match.group(0))
        # Find an IPv4 address on the same line.
        ip_match = re.search(r"(\d{1,3}\.){3}\d{1,3}", line)
        if ip_match:
            result[ip_match.group(0)] = mac
    return result


def _ping(host: str, timeout: float = 0.6) -> bool:
    """Send a single ICMP echo. Used to populate the ARP cache."""
    try:
        if platform.system() == "Windows":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), host]
        return subprocess.call(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1.0,
        ) == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _warm_arp(network: ipaddress.IPv4Network) -> None:
    """Populate the ARP cache by pinging every host on ``network`` quickly.

    Networks larger than /24 are skipped — we don't want to flood beyond
    the user's local segment.
    """
    if network.num_addresses > 256:
        return
    hosts = [str(h) for h in network.hosts()]
    with ThreadPoolExecutor(max_workers=64) as pool:
        list(pool.map(_ping, hosts))


def _try_tcp(host: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


@dataclass
class RediscoveryResult:
    camera_id: str
    new_host: Optional[str]
    mac: str


class _RediscoverWorker(QObject):
    """Runs the actual rediscovery on a worker thread."""

    finished = pyqtSignal(object)  # RediscoveryResult

    def __init__(self, camera_id: str, mac: str,
                 rtsp_port: int, last_host: str = "") -> None:
        super().__init__()
        self._camera_id = camera_id
        self._mac = _normalize_mac(mac)
        self._rtsp_port = rtsp_port
        self._last_host = last_host

    @pyqtSlot()
    def run(self) -> None:
        result = RediscoveryResult(
            camera_id=self._camera_id,
            new_host=None,
            mac=self._mac,
        )
        if not self._mac:
            self.finished.emit(result)
            return

        _log.info("Rediscovery start mac=%s last_host=%s",
                  self._mac, self._last_host)

        for network in _local_ipv4_subnets():
            _warm_arp(network)
            arp = _arp_table()
            candidate_ips = [ip for ip, mac in arp.items() if mac == self._mac]
            for ip in candidate_ips:
                # Verify the device is reachable on the RTSP port — there's
                # no point handing back an IP we can't actually open.
                if _try_tcp(ip, self._rtsp_port):
                    result.new_host = ip
                    _log.info("Rediscovery hit mac=%s host=%s", self._mac, ip)
                    self.finished.emit(result)
                    return
            _log.debug("Rediscovery: no MAC match in %s (entries=%d)",
                       network, len(arp))

        _log.info("Rediscovery miss mac=%s", self._mac)
        self.finished.emit(result)


def fingerprint_camera_mac(host: str) -> str:
    """Best-effort lookup: ARP-warm the host and return the MAC, if any."""
    if not host:
        return ""
    _ping(host, timeout=0.6)
    mac = _arp_table().get(host, "")
    return _normalize_mac(mac)


class IpRediscoverer(QObject):
    """Owner-friendly API that spawns a one-shot worker thread.

    Emit :pyattr:`completed` once the scan finishes (with or without a
    match). The owner is responsible for keeping the instance alive until
    the signal fires.
    """

    completed = pyqtSignal(object)  # RediscoveryResult

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[_RediscoverWorker] = None

    def start(self, camera_id: str, mac: str, rtsp_port: int,
              last_host: str = "") -> None:
        if self._thread is not None:
            return  # already running
        thread = QThread(self)
        worker = _RediscoverWorker(camera_id, mac, rtsp_port, last_host)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_finished(self, result: object) -> None:
        self._thread = None
        self._worker = None
        self.completed.emit(result)


def schedule_ip_rediscovery(parent: QObject, camera_id: str, mac: str,
                            rtsp_port: int, last_host: str,
                            on_result) -> Optional[IpRediscoverer]:
    """Convenience helper used by the main window."""
    if not mac:
        return None
    rediscover = IpRediscoverer(parent)
    rediscover.completed.connect(on_result)
    rediscover.start(camera_id, mac, rtsp_port, last_host)
    return rediscover
