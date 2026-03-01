"""RAM diagnostics — total, available, slots, type."""

import re
import subprocess
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("diag.memory")


@dataclass
class MemorySlot:
    locator: str = ""
    size_mb: int = 0
    type: str = "Unknown"
    speed_mhz: int = 0
    manufacturer: str = "Unknown"


@dataclass
class MemoryInfo:
    total_mb: int = 0
    available_mb: int = 0
    used_mb: int = 0
    swap_total_mb: int = 0
    swap_used_mb: int = 0
    slots: list[MemorySlot] = field(default_factory=list)
    max_capacity_mb: int = 0
    usage_percent: float = 0.0


def collect() -> MemoryInfo:
    info = MemoryInfo()
    _parse_meminfo(info)
    _parse_dmidecode(info)
    return info


def _parse_meminfo(info: MemoryInfo) -> None:
    try:
        with open("/proc/meminfo", "r") as fh:
            text = fh.read()
    except Exception as exc:
        log.warning("Cannot read /proc/meminfo: %s", exc)
        return

    values: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) == 2:
            key = parts[0].strip()
            val = parts[1].strip().split()[0]
            values[key] = int(val)

    info.total_mb = values.get("MemTotal", 0) // 1024
    info.available_mb = values.get("MemAvailable", values.get("MemFree", 0)) // 1024
    info.used_mb = info.total_mb - info.available_mb
    info.swap_total_mb = values.get("SwapTotal", 0) // 1024
    info.swap_used_mb = (values.get("SwapTotal", 0) - values.get("SwapFree", 0)) // 1024
    if info.total_mb > 0:
        info.usage_percent = round(info.used_mb / info.total_mb * 100, 1)


def _parse_dmidecode(info: MemoryInfo) -> None:
    try:
        output = subprocess.check_output(
            ["dmidecode", "-t", "memory"], text=True, timeout=10, stderr=subprocess.DEVNULL
        )
    except Exception as exc:
        log.debug("dmidecode not available: %s", exc)
        return

    # Max capacity
    m = re.search(r"Maximum Capacity:\s*(\d+)\s*(GB|MB|TB)", output)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        info.max_capacity_mb = val * {"MB": 1, "GB": 1024, "TB": 1024 * 1024}.get(unit, 1)

    # Individual DIMMs
    for block in output.split("Memory Device"):
        slot = MemorySlot()
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("Size:"):
                size_str = line.split(":", 1)[1].strip()
                if "No Module" in size_str or "Not Installed" in size_str:
                    continue
                parts = size_str.split()
                if len(parts) >= 2:
                    try:
                        val = int(parts[0])
                        unit = parts[1]
                        slot.size_mb = val * {"MB": 1, "GB": 1024}.get(unit, 1)
                    except ValueError:
                        pass
            elif line.startswith("Type:"):
                slot.type = line.split(":", 1)[1].strip()
            elif line.startswith("Speed:"):
                speed_str = line.split(":", 1)[1].strip().split()[0]
                try:
                    slot.speed_mhz = int(speed_str)
                except ValueError:
                    pass
            elif line.startswith("Locator:"):
                slot.locator = line.split(":", 1)[1].strip()
            elif line.startswith("Manufacturer:"):
                slot.manufacturer = line.split(":", 1)[1].strip()

        if slot.size_mb > 0:
            info.slots.append(slot)
