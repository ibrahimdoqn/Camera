"""Legacy shim — the app now decodes everything via libVLC.

The old OpenCV / FFmpeg workers used to live here. Both have been
retired in favour of :class:`~app.vlc_view.VLCFrameWorker`, which routes
RTSP + hardware-accelerated decode through libVLC and delivers frames
into the same Qt paint pipeline that already drives zoom, pan and the
overlay chip. VLC now picks the GPU decode path on its own; there is no
user-visible hardware acceleration setting to plumb through.

The alias below keeps the module importable from any older code path
that still references ``StreamWorker`` directly.
"""
from __future__ import annotations

from .vlc_view import VLCFrameWorker
from .vlc_view import VLCFrameWorker as StreamWorker  # legacy alias

__all__ = ["StreamWorker", "VLCFrameWorker"]
