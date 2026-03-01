"""CPU diagnostics — model, frequency, cores, temperature, usage."""

import re
import subprocess
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("diag.cpu")


@dataclass
class CPUInfo:
    model: str = "Unknown"
    vendor: str = "Unknown"
    cores_physical: int = 0
    cores_logical: int = 0
    frequency_mhz: float = 0.0
    frequency_max_mhz: float = 0.0
    temperature_c: float | None = None
    architecture: str = "Unknown"
    flags: list[str] = field(default_factory=list)
    usage_percent: float | None = None


def collect() -> CPUInfo:
    info = CPUInfo()
    try:
        _parse_cpuinfo(info)
    except Exception as exc:
        log.warning("Failed to read /proc/cpuinfo: %s", exc)
    try:
        _read_temperature(info)
    except Exception as exc:
        log.debug("Temperature unavailable: %s", exc)
    try:
        _read_usage(info)
    except Exception as exc:
        log.debug("Usage unavailable: %s", exc)
    return info


def _parse_cpuinfo(info: CPUInfo) -> None:
    with open("/proc/cpuinfo", "r") as fh:
        text = fh.read()

    for line in text.splitlines():
        if line.startswith("model name"):
            info.model = line.split(":", 1)[1].strip()
        elif line.startswith("vendor_id"):
            info.vendor = line.split(":", 1)[1].strip()
        elif line.startswith("cpu MHz"):
            info.frequency_mhz = float(line.split(":", 1)[1].strip())
        elif line.startswith("flags"):
            info.flags = line.split(":", 1)[1].strip().split()

    # Count cores
    physical_ids = set()
    logical_count = 0
    for block in text.split("\n\n"):
        if "processor" in block:
            logical_count += 1
        m = re.search(r"core id\s*:\s*(\d+)", block)
        if m:
            physical_ids.add(m.group(1))

    info.cores_logical = logical_count
    info.cores_physical = len(physical_ids) or logical_count

    # Architecture via uname
    try:
        info.architecture = subprocess.check_output(
            ["uname", "-m"], text=True, timeout=5
        ).strip()
    except Exception:
        pass

    # Max frequency
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq") as fh:
            info.frequency_max_mhz = int(fh.read().strip()) / 1000
    except Exception:
        info.frequency_max_mhz = info.frequency_mhz


def _read_temperature(info: CPUInfo) -> None:
    """Try to read CPU temperature from thermal zones or sensors."""
    # Method 1: thermal zone
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as fh:
            info.temperature_c = int(fh.read().strip()) / 1000.0
            return
    except Exception:
        pass

    # Method 2: sensors command
    try:
        output = subprocess.check_output(["sensors", "-u"], text=True, timeout=5)
        for line in output.splitlines():
            if "temp1_input" in line:
                info.temperature_c = float(line.split(":", 1)[1].strip())
                return
    except Exception:
        pass


def _read_usage(info: CPUInfo) -> None:
    try:
        import psutil
        info.usage_percent = psutil.cpu_percent(interval=0.5)
    except ImportError:
        pass
