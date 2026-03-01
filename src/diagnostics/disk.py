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


# Critical SMART attributes
_CRITICAL_ATTRS = {
    5: "Reallocated_Sector_Ct",
    187: "Reported_Uncorrect",
    188: "Command_Timeout",
    196: "Reallocated_Event_Count",
    197: "Current_Pending_Sector",
    198: "Offline_Uncorrectable",
}


def collect() -> DiskInfo:
    info = DiskInfo()
    devices = _list_block_devices()
    for dev_path in devices:
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

    devices = []
    for line in output.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "disk":
            devices.append(parts[0])
    return devices


def _read_smart(disk: DiskDevice) -> None:
    """Read S.M.A.R.T. data using smartctl."""
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

    # Device type
    rotation = data.get("rotation_rate", 0)
    if rotation == 0:
        disk.type = "SSD"
    elif isinstance(rotation, int) and rotation > 0:
        disk.type = "HDD"
    if "nvme" in disk.device:
        disk.type = "NVMe"
        disk.interface = "NVMe"
    else:
        disk.interface = data.get("interface_speed", {}).get("current", {}).get("string", "SATA")

    # Overall health
    smart_status = data.get("smart_status", {}).get("passed")
    if smart_status is not None:
        disk.smart_healthy = smart_status

    # Temperature
    temp = data.get("temperature", {}).get("current")
    if temp is not None:
        disk.temperature_c = temp

    # Power-on hours
    poh = data.get("power_on_time", {}).get("hours")
    if poh is not None:
        disk.power_on_hours = poh

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
        if sa.value <= sa.threshold and sa.threshold > 0:
            sa.status = "failing"
        elif sa.id in _CRITICAL_ATTRS and sa.value < sa.worst:
            sa.status = "warning"
        disk.smart_attrs.append(sa)


def _read_partitions(disk: DiskDevice) -> None:
    """Read partition information from lsblk."""
    try:
        output = subprocess.check_output(
            ["lsblk", "-Jpo", "NAME,FSTYPE,SIZE,MOUNTPOINT,FSUSED", disk.device],
            text=True, timeout=10,
        )
        data = json.loads(output)
    except Exception as exc:
        log.debug("lsblk partition read failed for %s: %s", disk.device, exc)
        return

    for dev in data.get("blockdevices", []):
        for child in dev.get("children", []):
            part = Partition(
                device=child.get("name", ""),
                filesystem=child.get("fstype", "") or "",
                mount_point=child.get("mountpoint", "") or "",
            )
            # Parse sizes
            size_str = child.get("size", "0")
            part.size_mb = _parse_size_to_mb(size_str)
            used_str = child.get("fsused") or "0"
            part.used_mb = _parse_size_to_mb(used_str)
            if part.size_mb > 0:
                part.usage_percent = round(part.used_mb / part.size_mb * 100, 1)
            disk.partitions.append(part)


def _parse_size_to_mb(s: str) -> int:
    """Convert human-readable size (e.g. '500G', '1.5T') to MB."""
    if not s or s == "0":
        return 0
    s = s.strip()
    multipliers = {"B": 1 / (1024 * 1024), "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}
    for suffix, mult in multipliers.items():
        if s.upper().endswith(suffix):
            try:
                return int(float(s[:-1]) * mult)
            except ValueError:
                return 0
    try:
        return int(s)
    except ValueError:
        return 0
