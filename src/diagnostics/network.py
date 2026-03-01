"""Network diagnostics — interfaces, connectivity, DNS."""

import subprocess
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("diag.network")


@dataclass
class NetworkInterface:
    name: str = ""
    mac: str = ""
    ipv4: str = ""
    ipv6: str = ""
    state: str = "unknown"  # up | down | unknown
    speed_mbps: int | None = None
    driver: str = ""


@dataclass
class NetworkInfo:
    interfaces: list[NetworkInterface] = field(default_factory=list)
    internet_available: bool = False
    dns_working: bool = False
    gateway: str = ""


def collect() -> NetworkInfo:
    info = NetworkInfo()
    _parse_ip_link(info)
    _read_gateway(info)
    _check_connectivity(info)
    return info


def _parse_ip_link(info: NetworkInfo) -> None:
    try:
        output = subprocess.check_output(
            ["ip", "-o", "link", "show"], text=True, timeout=10
        )
    except Exception as exc:
        log.warning("ip link show failed: %s", exc)
        return

    for line in output.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        iface = NetworkInterface()
        iface.name = parts[1].strip().split("@")[0]
        if iface.name == "lo":
            continue
        iface.state = "up" if "state UP" in line else "down"

        # Read MAC
        idx = line.find("link/ether")
        if idx >= 0:
            iface.mac = line[idx:].split()[1]

        # Read IP address
        try:
            addr_out = subprocess.check_output(
                ["ip", "-o", "addr", "show", iface.name],
                text=True, timeout=5,
            )
            for aline in addr_out.splitlines():
                if "inet " in aline:
                    iface.ipv4 = aline.split("inet ")[1].split()[0]
                elif "inet6 " in aline and "scope global" in aline:
                    iface.ipv6 = aline.split("inet6 ")[1].split()[0]
        except Exception:
            pass

        # Read speed
        try:
            with open(f"/sys/class/net/{iface.name}/speed") as fh:
                iface.speed_mbps = int(fh.read().strip())
        except Exception:
            pass

        info.interfaces.append(iface)


def _read_gateway(info: NetworkInfo) -> None:
    try:
        output = subprocess.check_output(
            ["ip", "route", "show", "default"], text=True, timeout=5
        )
        parts = output.strip().split()
        if "via" in parts:
            info.gateway = parts[parts.index("via") + 1]
    except Exception:
        pass


def _check_connectivity(info: NetworkInfo) -> None:
    # DNS check
    try:
        subprocess.check_output(
            ["nslookup", "google.com"], text=True, timeout=5, stderr=subprocess.DEVNULL
        )
        info.dns_working = True
    except Exception:
        info.dns_working = False

    # Internet check (ping)
    try:
        subprocess.check_call(
            ["ping", "-c", "1", "-W", "3", "8.8.8.8"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
        info.internet_available = True
    except Exception:
        info.internet_available = False
