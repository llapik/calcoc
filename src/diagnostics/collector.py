"""Unified system information collector — aggregates all diagnostics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import Any

from src.core.logger import get_logger
from src.diagnostics import cpu, memory, disk, gpu, motherboard, os_info, network

log = get_logger("diag.collector")


@dataclass
class SystemSnapshot:
    cpu: cpu.CPUInfo | None = None
    memory: memory.MemoryInfo | None = None
    disk: disk.DiskInfo | None = None
    gpu: gpu.GPUInfo | None = None
    motherboard: motherboard.MotherboardInfo | None = None
    os: os_info.OSInfo | None = None
    network: network.NetworkInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_text(self) -> str:
        """Return a human-readable summary of the system."""
        lines = ["=== System Summary ==="]

        if self.cpu:
            lines.append(f"CPU: {self.cpu.model} ({self.cpu.cores_physical}C/{self.cpu.cores_logical}T, {self.cpu.frequency_mhz:.0f} MHz)")
            if self.cpu.temperature_c is not None:
                lines.append(f"  Temperature: {self.cpu.temperature_c}°C")

        if self.memory:
            lines.append(f"RAM: {self.memory.total_mb} MB total, {self.memory.available_mb} MB available ({self.memory.usage_percent}% used)")
            if self.memory.slots:
                for slot in self.memory.slots:
                    lines.append(f"  Slot {slot.locator}: {slot.size_mb} MB {slot.type} @ {slot.speed_mhz} MHz")

        if self.disk:
            for d in self.disk.devices:
                health = "Healthy" if d.smart_healthy else ("FAILING" if d.smart_healthy is False else "Unknown")
                lines.append(f"Disk: {d.model} ({d.size_gb} GB {d.type}) — S.M.A.R.T.: {health}")
                if d.power_on_hours is not None:
                    lines.append(f"  Power-on: {d.power_on_hours} hours")

        if self.gpu:
            for g in self.gpu.devices:
                vram = f", {g.vram_mb} MB VRAM" if g.vram_mb else ""
                lines.append(f"GPU: {g.name} ({g.vendor}{vram})")

        if self.motherboard:
            mb = self.motherboard
            lines.append(f"Motherboard: {mb.manufacturer} {mb.product_name}")
            lines.append(f"BIOS: {mb.bios_vendor} {mb.bios_version} ({mb.bios_date})")
            lines.append(f"Chassis: {mb.chassis_type}")

        if self.os:
            lines.append(f"Boot mode: {self.os.boot_mode}")
            for o in self.os.detected:
                lines.append(f"OS: {o.name} {o.version} on {o.partition}")

        if self.network:
            net = self.network
            lines.append(f"Internet: {'Available' if net.internet_available else 'Not available'}")
            for iface in net.interfaces:
                lines.append(f"  {iface.name}: {iface.ipv4 or 'no IP'} ({iface.state})")

        return "\n".join(lines)


_COLLECTORS = [
    ("cpu", cpu.collect, "CPU"),
    ("memory", memory.collect, "Memory"),
    ("disk", disk.collect, "Disk"),
    ("gpu", gpu.collect, "GPU"),
    ("motherboard", motherboard.collect, "Motherboard"),
    ("os", os_info.collect, "OS"),
    ("network", network.collect, "Network"),
]


class SystemCollector:
    """Runs all diagnostic modules and returns a snapshot."""

    def collect_all(self) -> SystemSnapshot:
        log.info("Starting full system scan…")
        snapshot = SystemSnapshot()
        with ThreadPoolExecutor(max_workers=len(_COLLECTORS)) as executor:
            futures = [
                (attr, executor.submit(self._safe, fn, label))
                for attr, fn, label in _COLLECTORS
            ]
            for attr, future in futures:
                setattr(snapshot, attr, future.result())
        log.info("System scan complete")
        return snapshot

    @staticmethod
    def _safe(fn, name: str):
        try:
            return fn()
        except Exception as exc:
            log.error("Module %s failed: %s", name, exc)
            return None
