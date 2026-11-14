"""Platform and run-mode detection.

The same code base runs in two modes:

* ``desktop`` — installed inside a running OS (Linux or Windows). Only actions that are safe
  on a live system are available.
* ``rescue`` — booted from the USB stick. Offline repairs (fsck, bootloader, registry) are possible.
"""

import os
import sys
from pathlib import Path

_RESCUE_DATA_DIR = "/mnt/usb_data"


def os_family() -> str:
    """Return ``linux``, ``windows``, ``macos`` or ``other``."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "other"


def run_mode() -> str:
    """Return ``rescue`` when started from the bootable USB, ``desktop`` otherwise."""
    return "rescue" if os.environ.get("CALCOC_MODE", "").lower() == "rescue" else "desktop"


def default_data_dir() -> Path:
    """Directory for journal, backups, telemetry and logs."""
    if override := os.environ.get("CALCOC_DATA_DIR"):
        return Path(override)
    if run_mode() == "rescue":
        return Path(_RESCUE_DATA_DIR)
    if os_family() == "windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "calcoc"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "calcoc"
