"""Tests for telemetry collector and failure predictor."""

import pytest

from src.diagnostics.cpu import CPUInfo
from src.diagnostics.memory import MemoryInfo
from src.diagnostics.disk import DiskInfo, DiskDevice
from src.diagnostics.collector import SystemSnapshot
from src.telemetry.collector import TelemetryCollector
from src.telemetry.predictor import predict, _linear_trend


@pytest.fixture
def telemetry(tmp_path):
    return TelemetryCollector(tmp_path / "telemetry.db")


def _make_snapshot(cpu_temp=50, ram_usage=40, disk_temp=35, smart_ok=True):
    return SystemSnapshot(
        cpu=CPUInfo(model="Test", temperature_c=cpu_temp, usage_percent=30),
        memory=MemoryInfo(total_mb=8192, available_mb=4096, used_mb=4096, usage_percent=ram_usage),
        disk=DiskInfo(devices=[
            DiskDevice(device="/dev/sda", model="Test Disk", temperature_c=disk_temp,
                       smart_healthy=smart_ok, power_on_hours=5000),
        ]),
    )


class TestTelemetryCollector:
    def test_record_and_retrieve(self, telemetry):
        snapshot = _make_snapshot()
        telemetry.record(snapshot, machine_id="test-machine")

        history = telemetry.get_history("test-machine")
        assert len(history) == 1
        assert history[0].cpu_temp == 50
        assert history[0].machine_id == "test-machine"

    def test_multiple_records(self, telemetry):
        for temp in [50, 55, 60]:
            snapshot = _make_snapshot(cpu_temp=temp)
            telemetry.record(snapshot, machine_id="test")

        history = telemetry.get_history("test")
        assert len(history) == 3

    def test_all_machines(self, telemetry):
        telemetry.record(_make_snapshot(), machine_id="machine-a")
        telemetry.record(_make_snapshot(), machine_id="machine-b")

        machines = telemetry.get_all_machines()
        assert set(machines) == {"machine-a", "machine-b"}


class TestPredictor:
    def test_linear_trend_rising(self):
        values = [30, 35, 40, 45, 50]
        trend = _linear_trend(values)
        assert trend > 0

    def test_linear_trend_stable(self):
        values = [40, 40, 40, 40]
        trend = _linear_trend(values)
        assert abs(trend) < 0.01

    def test_predict_needs_data(self, telemetry):
        # With <2 data points, no predictions
        telemetry.record(_make_snapshot(), machine_id="test")
        report = predict(telemetry, "test")
        assert len(report.predictions) == 0

    def test_predict_with_history(self, telemetry):
        # Record enough data for analysis
        for i in range(5):
            telemetry.record(_make_snapshot(cpu_temp=50 + i * 2), machine_id="test")

        report = predict(telemetry, "test")
        assert report.data_points == 5
