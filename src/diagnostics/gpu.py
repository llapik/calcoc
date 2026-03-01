"""GPU diagnostics — model, VRAM, driver, temperature."""

import re
import subprocess
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("diag.gpu")


@dataclass
class GPUDevice:
    name: str = "Unknown"
    vendor: str = "Unknown"
    pci_id: str = ""
    driver: str = "Unknown"
    vram_mb: int = 0
    temperature_c: int | None = None
    clock_mhz: int | None = None


@dataclass
class GPUInfo:
    devices: list[GPUDevice] = field(default_factory=list)


def collect() -> GPUInfo:
    info = GPUInfo()
    _parse_lspci(info)
    _try_nvidia_smi(info)
    return info


def _parse_lspci(info: GPUInfo) -> None:
    """Detect GPUs via lspci."""
    try:
        output = subprocess.check_output(
            ["lspci", "-mm", "-nn"], text=True, timeout=10, stderr=subprocess.DEVNULL
        )
    except Exception as exc:
        log.warning("lspci failed: %s", exc)
        return

    for line in output.splitlines():
        if "VGA" in line or "3D controller" in line or "Display" in line:
            gpu = GPUDevice()
            # Extract PCI id
            m = re.match(r"^(\S+)", line)
            if m:
                gpu.pci_id = m.group(1)
            # Extract device name from quoted fields
            quoted = re.findall(r'"([^"]*)"', line)
            if len(quoted) >= 3:
                gpu.vendor = quoted[1]
                gpu.name = quoted[2]

            # Attempt to read driver
            try:
                detail = subprocess.check_output(
                    ["lspci", "-v", "-s", gpu.pci_id],
                    text=True, timeout=10, stderr=subprocess.DEVNULL,
                )
                dm = re.search(r"Kernel driver in use:\s*(\S+)", detail)
                if dm:
                    gpu.driver = dm.group(1)
            except Exception:
                pass

            info.devices.append(gpu)


def _try_nvidia_smi(info: GPUInfo) -> None:
    """Enrich NVIDIA GPU info via nvidia-smi if available."""
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,temperature.gpu,clocks.gr",
                "--format=csv,noheader,nounits",
            ],
            text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return

    for i, line in enumerate(output.strip().splitlines()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        # Try to match with existing device, or add new
        target = info.devices[i] if i < len(info.devices) else GPUDevice()
        if i >= len(info.devices):
            info.devices.append(target)

        target.name = parts[0] or target.name
        target.vendor = "NVIDIA"
        try:
            target.vram_mb = int(parts[1])
        except ValueError:
            pass
        try:
            target.temperature_c = int(parts[2])
        except ValueError:
            pass
        try:
            target.clock_mhz = int(parts[3])
        except ValueError:
            pass
