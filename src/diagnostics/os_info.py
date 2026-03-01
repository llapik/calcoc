"""Detect installed operating systems on local drives."""

import os
import re
import subprocess
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("diag.os")


@dataclass
class DetectedOS:
    name: str = "Unknown"
    version: str = ""
    build: str = ""
    architecture: str = ""
    partition: str = ""
    boot_type: str = ""  # UEFI | Legacy


@dataclass
class OSInfo:
    detected: list[DetectedOS] = field(default_factory=list)
    boot_mode: str = "Unknown"  # UEFI | Legacy


def collect() -> OSInfo:
    info = OSInfo()
    info.boot_mode = _detect_boot_mode()
    _scan_mounted_filesystems(info)
    return info


def _detect_boot_mode() -> str:
    if os.path.isdir("/sys/firmware/efi"):
        return "UEFI"
    return "Legacy"


def _scan_mounted_filesystems(info: OSInfo) -> None:
    """Look for OS signatures on mounted partitions."""
    try:
        output = subprocess.check_output(
            ["lsblk", "-rpo", "NAME,MOUNTPOINT,FSTYPE"], text=True, timeout=10
        )
    except Exception:
        return

    for line in output.strip().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        device = parts[0]
        mount = parts[1] if len(parts) >= 2 and parts[1] != "" else None
        if not mount or mount == "":
            continue

        # Check for Windows
        windows_path = os.path.join(mount, "Windows", "System32")
        if os.path.isdir(windows_path):
            detected = DetectedOS(
                name="Windows",
                partition=device,
                boot_type=info.boot_mode,
            )
            _detect_windows_version(mount, detected)
            info.detected.append(detected)
            continue

        # Check for Linux
        os_release = os.path.join(mount, "etc", "os-release")
        if os.path.isfile(os_release):
            detected = DetectedOS(partition=device, boot_type=info.boot_mode)
            _parse_os_release(os_release, detected)
            info.detected.append(detected)
            continue


def _detect_windows_version(mount: str, detected: DetectedOS) -> None:
    """Try to extract Windows version from the registry or SOFTWARE hive."""
    # Quick heuristic: check explorer.exe version
    try:
        reg_path = os.path.join(mount, "Windows", "System32", "config", "SOFTWARE")
        if os.path.isfile(reg_path):
            from python_registry import Registry
            reg = Registry.Registry(reg_path)
            key = reg.open("Microsoft\\Windows NT\\CurrentVersion")
            detected.name = "Windows"
            for v in key.values():
                if v.name() == "ProductName":
                    detected.version = v.value()
                elif v.name() == "CurrentBuild":
                    detected.build = v.value()
    except Exception as exc:
        log.debug("Windows version detection failed: %s", exc)
        detected.version = "Unknown version"


def _parse_os_release(path: str, detected: DetectedOS) -> None:
    try:
        with open(path, "r") as fh:
            text = fh.read()
        for line in text.splitlines():
            if line.startswith("PRETTY_NAME="):
                detected.name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("VERSION_ID="):
                detected.version = line.split("=", 1)[1].strip().strip('"')
    except Exception as exc:
        log.debug("Cannot parse os-release at %s: %s", path, exc)
        detected.name = "Linux (unknown)"
