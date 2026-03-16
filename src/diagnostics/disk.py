"""Disk diagnostics — devices, partitions, S.M.A.R.T. health."""

import json
import subprocess
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("diag.disk")


@dataclass
class SmartAttribute:
    id: int = 0
    name: str = ""
    value: int = 0
    worst: int = 0
    threshold: int = 0
    raw_value: str = ""
    status: str = "ok"  # ok | warning | failing


@dataclass
class Partition:
    device: str = ""
    mount_point: str = ""
    filesystem: str = ""
    size_mb: int = 0
    used_mb: int = 0
    usage_percent: float = 0.0


@dataclass
class DiskDevice:
    device: str = ""
    model: str = "Unknown"
    serial: str = ""
    size_gb: float = 0.0
    type: str = "Unknown"  # HDD | SSD | NVMe
    interface: str = "Unknown"  # SATA | NVMe | USB
    smart_healthy: bool | None = None
    smart_attrs: list[SmartAttribute] = field(default_factory=list)
    temperature_c: int | None = None
    power_on_hours: int | None = None
    partitions: list[Partition] = field(default_factory=list)


@dataclass
class DiskInfo:
    devices: list[DiskDevice] = field(default_factory=list)


# Critical SMART attributes that indicate imminent failure
_CRITICAL_ATTRS = {5, 187, 188, 196, 197, 198}

# Size multipliers for _parse_size_to_mb (last character → MB factor)
_SIZE_MULTIPLIERS: dict[str, float] = {
    "B": 1 / (1024 * 1024), "K": 1 / 1024,
    "M": 1.0, "G": 1024.0, "T": 1024.0 * 1024,
}


def collect() -> DiskInfo:
    info = DiskInfo()
    for dev_path in _list_block_devices():
        disk = DiskDevice(device=dev_path)
        _read_smart(disk)
        _read_partitions(disk)
        info.devices.append(disk)
    return info


def _list_block_devices() -> list[str]:
    """Return a list of physical block device paths (/dev/sdX, /dev/nvmeXnY)."""
    try:
        output = subprocess.check_output(
            ["lsblk", "-dnpo", "NAME,TYPE"], text=True, timeout=10
        )
    except Exception as exc:
        log.warning("lsblk failed: %s", exc)
        return []

    return [
        parts[0]
        for line in output.strip().splitlines()
        if len(parts := line.split()) >= 2 and parts[1] == "disk"
    ]


def _read_smart(disk: DiskDevice) -> None:
    """Read S.M.A.R.T. data using smartctl (JSON output)."""
    try:
        output = subprocess.check_output(
            ["smartctl", "-a", "-j", disk.device],
            text=True, timeout=30, stderr=subprocess.DEVNULL,
        )
        data = json.loads(output)
    except Exception as exc:
        log.debug("smartctl failed for %s: %s", disk.device, exc)
        return

    disk.model = data.get("model_name", disk.model)
    disk.serial = data.get("serial_number", "")

    # Size
    capacity = data.get("user_capacity", {})
    if "bytes" in capacity:
        disk.size_gb = round(capacity["bytes"] / (1024 ** 3), 1)

    # Device type — NVMe check before rotation_rate
    if "nvme" in disk.device.lower():
        disk.type = "NVMe"
        disk.interface = "NVMe"
    else:
        rotation = data.get("rotation_rate", 0)
        disk.type = "SSD" if rotation == 0 else "HDD"
        disk.interface = (
            data.get("interface_speed", {}).get("current", {}).get("string", "SATA")
        )

    # Overall health
    smart_status = data.get("smart_status", {}).get("passed")
    if smart_status is not None:
        disk.smart_healthy = bool(smart_status)

    # Temperature
    temp = data.get("temperature", {}).get("current")
    if temp is not None:
        disk.temperature_c = int(temp)

    # Power-on hours
    poh = data.get("power_on_time", {}).get("hours")
    if poh is not None:
        disk.power_on_hours = int(poh)

    # SMART attributes
    for attr in data.get("ata_smart_attributes", {}).get("table", []):
        sa = SmartAttribute(
            id=attr.get("id", 0),
            name=attr.get("name", ""),
            value=attr.get("value", 0),
            worst=attr.get("worst", 0),
            threshold=attr.get("thresh", 0),
            raw_value=str(attr.get("raw", {}).get("string", "")),
        )
        if sa.threshold > 0 and sa.value <= sa.threshold:
            sa.status = "failing"
        elif sa.id in _CRITICAL_ATTRS and sa.value < sa.worst:
            sa.status = "warning"
        disk.smart_attrs.append(sa)


def _read_partitions(disk: DiskDevice) -> None:
    """Read partition information from lsblk.

    Uses NAME,FSTYPE,SIZE,MOUNTPOINT only — FSUSED is unreliable on older lsblk.
    Actual used space is read from a single batched df call for all mounted partitions.
    """
    try:
        output = subprocess.check_output(
            ["lsblk", "-Jpo", "NAME,FSTYPE,SIZE,MOUNTPOINT", disk.device],
            text=True, timeout=10,
        )
        data = json.loads(output)
    except Exception as exc:
        log.debug("lsblk partition read failed for %s: %s", disk.device, exc)
        return

    parts: list[Partition] = []
    for dev in data.get("blockdevices", []):
        for child in dev.get("children", []):
            # mountpoint can be a string or list in newer lsblk
            mountpoint = child.get("mountpoint") or ""
            if isinstance(mountpoint, list):
                mountpoint = mountpoint[0] if mountpoint else ""

            part = Partition(
                device=child.get("name", ""),
                filesystem=child.get("fstype", "") or "",
                mount_point=mountpoint,
            )
            part.size_mb = _parse_size_to_mb(child.get("size", "0"))
            parts.append(part)

    # One df call for all mounted partitions instead of one per partition
    mounted_points = [p.mount_point for p in parts if p.mount_point]
    usage_map = _df_used_mb_batch(mounted_points)

    for part in parts:
        if part.mount_point and part.mount_point in usage_map:
            part.used_mb = usage_map[part.mount_point]
            if part.size_mb > 0:
                part.usage_percent = round(part.used_mb / part.size_mb * 100, 1)
        disk.partitions.append(part)


def _df_used_mb_batch(mount_points: list[str]) -> dict[str, int]:
    """Return used space in MB for multiple mount points via a single df call."""
    if not mount_points:
        return {}
    try:
        # Filter out any path that starts with '-' to prevent option injection,
        # then add '--' to stop option processing entirely.
        safe_points = [p for p in mount_points if not p.startswith("-")]
        output = subprocess.check_output(
            ["df", "-BM", "--output=target,used", "--"] + safe_points,
            text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
        result: dict[str, int] = {}
        for line in output.strip().splitlines()[1:]:  # skip header
            cols = line.split()
            if len(cols) >= 2:
                try:
                    result[cols[0]] = int(cols[1].rstrip("M"))
                except ValueError:
                    pass
        return result
    except Exception:
        return {}


def _parse_size_to_mb(s: str) -> int:
    """Convert human-readable size (e.g. '500G', '1.5T') to MB."""
    if not s or s == "0":
        return 0
    s = s.strip()
    mult = _SIZE_MULTIPLIERS.get(s[-1].upper())
    if mult is not None:
        try:
            return int(float(s[:-1]) * mult)
        except ValueError:
            return 0
    try:
        return int(s)
    except ValueError:
        return 0
