"""Telemetry data collector — stores hardware parameters over time."""

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from src.core.logger import get_logger
from src.diagnostics.collector import SystemSnapshot

log = get_logger("telemetry.collector")


@dataclass
class TelemetryRecord:
    timestamp: float = 0.0
    machine_id: str = ""
    cpu_temp: float | None = None
    cpu_usage: float | None = None
    ram_usage_pct: float | None = None
    disk_temps: str = ""  # JSON dict: {device: temp}
    smart_status: str = ""  # JSON dict: {device: healthy}
    power_on_hours: str = ""  # JSON dict: {device: hours}
    gpu_temp: float | None = None


class TelemetryCollector:
    """Accumulates hardware telemetry data across boot sessions."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    machine_id TEXT DEFAULT '',
                    cpu_temp REAL,
                    cpu_usage REAL,
                    ram_usage_pct REAL,
                    disk_temps TEXT DEFAULT '{}',
                    smart_status TEXT DEFAULT '{}',
                    power_on_hours TEXT DEFAULT '{}',
                    gpu_temp REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_telemetry_machine
                ON telemetry(machine_id, timestamp)
            """)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record(self, snapshot: SystemSnapshot, machine_id: str = "") -> None:
        """Save a telemetry snapshot to the database."""
        import json

        if not machine_id:
            machine_id = self._derive_machine_id(snapshot)

        disk_temps = {}
        smart_status = {}
        poh = {}
        if snapshot.disk:
            for d in snapshot.disk.devices:
                if d.temperature_c is not None:
                    disk_temps[d.device] = d.temperature_c
                if d.smart_healthy is not None:
                    smart_status[d.device] = d.smart_healthy
                if d.power_on_hours is not None:
                    poh[d.device] = d.power_on_hours

        gpu_temp = None
        if snapshot.gpu and snapshot.gpu.devices:
            for g in snapshot.gpu.devices:
                if g.temperature_c is not None:
                    gpu_temp = g.temperature_c
                    break

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO telemetry
                   (timestamp, machine_id, cpu_temp, cpu_usage, ram_usage_pct,
                    disk_temps, smart_status, power_on_hours, gpu_temp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    time.time(),
                    machine_id,
                    snapshot.cpu.temperature_c if snapshot.cpu else None,
                    snapshot.cpu.usage_percent if snapshot.cpu else None,
                    snapshot.memory.usage_percent if snapshot.memory else None,
                    json.dumps(disk_temps),
                    json.dumps(smart_status),
                    json.dumps(poh),
                    gpu_temp,
                ),
            )
        log.info("Telemetry recorded for machine %s", machine_id)

    def get_history(self, machine_id: str, limit: int = 100) -> list[TelemetryRecord]:
        """Retrieve telemetry history for a specific machine."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM telemetry WHERE machine_id = ? ORDER BY timestamp DESC LIMIT ?",
                (machine_id, limit),
            ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def get_all_machines(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT machine_id FROM telemetry"
            ).fetchall()
            return [r["machine_id"] for r in rows]

    @staticmethod
    def _derive_machine_id(snapshot: SystemSnapshot) -> str:
        """Create a machine identifier from hardware info."""
        parts = []
        if snapshot.motherboard:
            parts.append(snapshot.motherboard.serial or snapshot.motherboard.product_name)
        if snapshot.cpu:
            parts.append(snapshot.cpu.model)
        return "_".join(parts)[:64] if parts else "unknown"

    @staticmethod
    def _row_to_record(row) -> TelemetryRecord:
        return TelemetryRecord(
            timestamp=row["timestamp"],
            machine_id=row["machine_id"],
            cpu_temp=row["cpu_temp"],
            cpu_usage=row["cpu_usage"],
            ram_usage_pct=row["ram_usage_pct"],
            disk_temps=row["disk_temps"],
            smart_status=row["smart_status"],
            power_on_hours=row["power_on_hours"],
            gpu_temp=row["gpu_temp"],
        )
