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
    hw_accel: str = "auto"  # auto | none | dxva2 | d3d11va | cuda
    decode_width: int = 0  # 0 = native
    reconnect_delay: float = 3.0
    show_overlay: bool = True
    sidebar_collapsed: bool = False


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
        cameras = [Camera(**c) for c in data.get("cameras", [])]
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
