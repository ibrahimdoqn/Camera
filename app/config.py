"""Persistent configuration for cameras and app settings."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    path = Path(base) / "TapoViewer"
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG_PATH = _config_dir() / "config.json"


@dataclass
class Camera:
    id: str
    name: str
    host: str
    username: str = ""
    password: str = ""
    rtsp_port: int = 554
    onvif_port: int = 2020
    stream: str = "stream1"  # Tapo: stream1 = HD, stream2 = SD
    custom_url: str = ""
    use_custom_url: bool = False
    audio_enabled: bool = False  # default: all cameras muted
    # Sidebar visibility: when False the camera stays in the sidebar (so
    # the user can re-enable it) but is removed from the grid and its
    # stream worker is stopped. Defaults to True so existing configs keep
    # showing every camera after upgrading.
    visible: bool = True
    # Captured the first time the camera is reached over the LAN; used by
    # the MAC-based IP rediscovery scan when the configured host stops
    # responding.
    mac_address: str = ""
    last_seen_host: str = ""

    @property
    def rtsp_url(self) -> str:
        if self.use_custom_url and self.custom_url:
            return self.custom_url
        creds = ""
        if self.username:
            creds = f"{self.username}:{self.password}@"
        return f"rtsp://{creds}{self.host}:{self.rtsp_port}/{self.stream}"

    @classmethod
    def new(cls, **kwargs: Any) -> "Camera":
        return cls(id=str(uuid.uuid4()), **kwargs)


@dataclass
class Settings:
    grid_columns: int = 2
    target_fps: int = 20
    # HW-accel path libVLC negotiates with the platform driver.
    #   auto    → let VLC pick (recommended; tries the best available)
    #   none    → force pure CPU decoding
    #   d3d11va → Windows DirectX 11
    #   dxva2   → Windows DirectX Video Acceleration 2
    #   cuda    → NVIDIA NVDEC (requires an NVIDIA GPU)
    #   qsv     → Intel Quick Sync (requires Intel integrated graphics)
    hw_accel: str = "auto"
    decode_width: int = 0  # 0 = native
    reconnect_delay: float = 3.0
    show_overlay: bool = True
    sidebar_collapsed: bool = False
    # File-based diagnostics. Logs land in %APPDATA%/TapoViewer/logs.
    logging_enabled: bool = False
    log_level: str = "INFO"
    # Rediscover a camera by MAC if its configured IP stops responding.
    ip_rediscovery_enabled: bool = True


@dataclass
class AppConfig:
    cameras: list[Camera] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cameras": [asdict(c) for c in self.cameras],
            "settings": asdict(self.settings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        cam_fields = Camera.__dataclass_fields__
        cameras = [
            Camera(**{k: v for k, v in c.items() if k in cam_fields})
            for c in data.get("cameras", [])
        ]
        settings_data = data.get("settings", {})
        settings = Settings(**{k: v for k, v in settings_data.items() if k in Settings.__dataclass_fields__})
        return cls(cameras=cameras, settings=settings)


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return AppConfig.from_dict(json.load(fh))
    except (json.JSONDecodeError, TypeError, KeyError):
        return AppConfig()


def save_config(config: AppConfig) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(config.to_dict(), fh, indent=2, ensure_ascii=False)
