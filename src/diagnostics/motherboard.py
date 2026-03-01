"""Motherboard and BIOS diagnostics via dmidecode."""

import subprocess
from dataclasses import dataclass

from src.core.logger import get_logger

log = get_logger("diag.motherboard")


@dataclass
class MotherboardInfo:
    manufacturer: str = "Unknown"
    product_name: str = "Unknown"
    serial: str = ""
    bios_vendor: str = "Unknown"
    bios_version: str = "Unknown"
    bios_date: str = ""
    chassis_type: str = "Unknown"  # Desktop, Laptop, Server, etc.


def collect() -> MotherboardInfo:
    info = MotherboardInfo()
    _parse_dmi_baseboard(info)
    _parse_dmi_bios(info)
    _parse_dmi_chassis(info)
    return info


def _run_dmi(type_num: int) -> str:
    try:
        return subprocess.check_output(
            ["dmidecode", "-t", str(type_num)],
            text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        log.debug("dmidecode -t %d failed: %s", type_num, exc)
        return ""


def _extract(text: str, key: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _parse_dmi_baseboard(info: MotherboardInfo) -> None:
    text = _run_dmi(2)
    info.manufacturer = _extract(text, "Manufacturer") or info.manufacturer
    info.product_name = _extract(text, "Product Name") or info.product_name
    info.serial = _extract(text, "Serial Number") or info.serial


def _parse_dmi_bios(info: MotherboardInfo) -> None:
    text = _run_dmi(0)
    info.bios_vendor = _extract(text, "Vendor") or info.bios_vendor
    info.bios_version = _extract(text, "Version") or info.bios_version
    info.bios_date = _extract(text, "Release Date") or info.bios_date


def _parse_dmi_chassis(info: MotherboardInfo) -> None:
    text = _run_dmi(3)
    info.chassis_type = _extract(text, "Type") or info.chassis_type
