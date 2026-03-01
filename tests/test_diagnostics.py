"""Tests for diagnostic modules."""

import pytest

from src.diagnostics.cpu import CPUInfo
from src.diagnostics.memory import MemoryInfo, MemorySlot
from src.diagnostics.disk import DiskDevice, DiskInfo, SmartAttribute, Partition, _parse_size_to_mb
from src.diagnostics.collector import SystemSnapshot, SystemCollector
from src.analysis.performance import analyze as analyze_performance, PerformanceReport


class TestParseSize:
    def test_gigabytes(self):
        assert _parse_size_to_mb("500G") == 500 * 1024

    def test_megabytes(self):
        assert _parse_size_to_mb("256M") == 256

    def test_terabytes(self):
        assert _parse_size_to_mb("1T") == 1024 * 1024

    def test_zero(self):
        assert _parse_size_to_mb("0") == 0

    def test_empty(self):
        assert _parse_size_to_mb("") == 0


class TestPerformanceAnalysis:
    def _make_snapshot(self, **kwargs) -> SystemSnapshot:
        snapshot = SystemSnapshot()
        if "cpu_temp" in kwargs:
            snapshot.cpu = CPUInfo(
                model="Test CPU",
                cores_physical=4,
                cores_logical=8,
                temperature_c=kwargs["cpu_temp"],
            )
        if "ram_total" in kwargs:
            snapshot.memory = MemoryInfo(
                total_mb=kwargs["ram_total"],
                available_mb=kwargs.get("ram_avail", kwargs["ram_total"] // 2),
                used_mb=kwargs["ram_total"] - kwargs.get("ram_avail", kwargs["ram_total"] // 2),
                usage_percent=round(
                    (kwargs["ram_total"] - kwargs.get("ram_avail", kwargs["ram_total"] // 2))
                    / kwargs["ram_total"] * 100, 1
                ),
            )
        if "disk_healthy" in kwargs:
            snapshot.disk = DiskInfo(devices=[
                DiskDevice(
                    device="/dev/sda",
                    model="Test Disk",
                    smart_healthy=kwargs["disk_healthy"],
                    type=kwargs.get("disk_type", "SSD"),
                ),
            ])
        return snapshot

    def test_healthy_system(self):
        snapshot = self._make_snapshot(cpu_temp=50, ram_total=16384, ram_avail=8192, disk_healthy=True)
        report = analyze_performance(snapshot)
        assert report.score >= 80
        assert report.summary

    def test_overheating_cpu(self):
        snapshot = self._make_snapshot(cpu_temp=90, ram_total=8192)
        report = analyze_performance(snapshot)
        critical = [b for b in report.bottlenecks if b.severity == "critical"]
        assert len(critical) > 0
        assert report.score < 100

    def test_low_ram(self):
        snapshot = self._make_snapshot(ram_total=2048, ram_avail=200)
        report = analyze_performance(snapshot)
        warnings = [b for b in report.bottlenecks if b.component == "ram"]
        assert len(warnings) > 0

    def test_failing_disk(self):
        snapshot = self._make_snapshot(disk_healthy=False)
        report = analyze_performance(snapshot)
        critical = [b for b in report.bottlenecks if b.severity == "critical"]
        assert len(critical) > 0
        assert report.score <= 70

    def test_hdd_recommendation(self):
        snapshot = self._make_snapshot(disk_healthy=True, disk_type="HDD")
        report = analyze_performance(snapshot)
        info = [b for b in report.bottlenecks if b.component == "disk" and b.severity == "info"]
        assert len(info) > 0


class TestSystemSnapshot:
    def test_summary_text(self):
        snapshot = SystemSnapshot(
            cpu=CPUInfo(model="Intel i7", cores_physical=4, cores_logical=8, frequency_mhz=3600),
            memory=MemoryInfo(total_mb=16384, available_mb=8000, used_mb=8384, usage_percent=51.2),
        )
        text = snapshot.summary_text()
        assert "Intel i7" in text
        assert "16384" in text

    def test_to_dict(self):
        snapshot = SystemSnapshot(
            cpu=CPUInfo(model="Test CPU"),
        )
        d = snapshot.to_dict()
        assert d["cpu"]["model"] == "Test CPU"
