# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Tapo Viewer (Windows, windowed/no-console).

Packaging notes:

* ONVIF PTZ pulls in ``onvif-zeep`` → ``zeep`` → ``lxml`` + a bag of
  runtime XSD/WSDL files. ``collect_submodules`` (the old spec) is
  not enough — PyInstaller does not pick up the WSDL data files or
  zeep's dynamic imports. We use ``collect_all`` for every package
  that has runtime resources, plus explicit hidden imports for the
  known-problematic deep modules (``zeep.wsdl.messages``,
  ``lxml._elementpath``, …). Without these, PTZ works in ``python
  main.py`` but silently dies inside the frozen ``.exe`` with
  ``FileNotFoundError`` on the WSDL or ``ModuleNotFoundError`` on
  a zeep sub-module.

* ``vlc`` (python-vlc) is a single-module shim around ``libvlc.dll``
  the user installed system-wide; only the Python side needs to be
  frozen, and ``libvlc.dll`` is picked up from ``PATH`` at runtime
  the same way it is in ``python main.py``.
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None


# --- Packages whose runtime resources must be bundled ----------------------
#
# ``collect_all`` returns (datas, binaries, hiddenimports) for a package and
# every one of its submodules — data files, C extensions, everything. It's
# the sledgehammer, but for zeep / lxml / onvif that's exactly what you
# want.
_PACKAGES_TO_BUNDLE = (
    "onvif",             # onvif-zeep — ships the WSDL directory
    "zeep",              # SOAP client used by onvif-zeep
    "lxml",              # XML parser — has native extensions
    "isodate",           # ISO-8601 handling required by zeep
    "requests_toolbelt", # MultipartEncoder used by zeep transports
    "pytz",              # tz data needed by zeep type handlers
)

datas = [
    ("Tapo.png", "."),
    ("Tapo.ico", "."),
]
binaries = []
hiddenimports = ["vlc"]

for _pkg in _PACKAGES_TO_BUNDLE:
    try:
        _d, _b, _h = collect_all(_pkg)
    except Exception:
        # Package not installed (optional dep) — skip cleanly.
        continue
    datas += _d
    binaries += _b
    hiddenimports += _h

# Extra hidden imports for zeep / lxml sub-modules that get imported
# through strings at runtime and are therefore invisible to PyInstaller's
# static scan.
hiddenimports += [
    "zeep.wsdl.messages",
    "zeep.wsdl.definitions",
    "zeep.transports",
    "zeep.plugins",
    "zeep.helpers",
    "lxml._elementpath",
    "lxml.etree",
    "lxml.objectify",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TapoViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,             # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="Tapo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TapoViewer",
)
