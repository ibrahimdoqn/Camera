"""Legacy shim — the app now decodes everything via libVLC.

The old OpenCV / FFmpeg workers used to live here. Both have been
retired in favour of :class:`~app.vlc_view.VLCFrameWorker`, which routes
RTSP + hardware-accelerated decode through libVLC and delivers frames
into the same Qt paint pipeline that already drives zoom, pan and the
overlay chip.

The re-exports below keep the module importable from any older code path
that hasn't been updated yet (nothing inside the app depends on them
directly), and expose the HW-accel detection helpers the Settings dialog
uses so callers only need one import.
"""
from __future__ import annotations

from .vlc_view import (
    ALL_HW_ACCEL_MODES,
    VLCFrameWorker,
    VLCFrameWorker as StreamWorker,  # legacy alias
    detect_supported_hw_accels,
)

__all__ = [
    "ALL_HW_ACCEL_MODES",
    "StreamWorker",
    "VLCFrameWorker",
    "detect_supported_hw_accels",
]
