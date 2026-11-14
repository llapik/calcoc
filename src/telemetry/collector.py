"""Telemetry data collector — stores hardware parameters over time."""

import json
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
    smart_attrs: str = ""  # JSON dict: {device: {attribute id: raw value}} for wear indicators

    def per_disk(self, column: str) -> dict:
        """Decode one of the JSON columns; empty dict if missing or damaged."""
        try:
            data = json.loads(getattr(self, column) or "{}")
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


# S.M.A.R.T. attributes whose raw value counts damage, so growth over time means wear
TRACKED_SMART_ATTRS = (5, 187, 197, 198)


def snapshot_to_record(snapshot: SystemSnapshot, timestamp: float | None = None) -> TelemetryRecord:
    """Reduce a snapshot to the values worth tracking over time."""
    disk_temps, smart_status, poh, attrs = {}, {}, {}, {}
    for d in (snapshot.disk.devices if snapshot.disk else []):
        if d.temperature_c is not None:
            disk_temps[d.device] = d.temperature_c
        if d.smart_healthy is not None:
            smart_status[d.device] = d.smart_healthy
        if d.power_on_hours is not None:
            poh[d.device] = d.power_on_hours
        raw = {}
        for a in d.smart_attrs:
            if a.id in TRACKED_SMART_ATTRS:
                try:
                    raw[str(a.id)] = int(str(a.raw_value).split()[0])
                except (ValueError, IndexError):
                    pass
        if raw:
            attrs[d.device] = raw

    gpu_temp = next(
        (g.temperature_c for g in (snapshot.gpu.devices if snapshot.gpu else []) if g.temperature_c is not None),
        None,
    )
    return TelemetryRecord(
        timestamp=timestamp if timestamp is not None else time.time(),
        cpu_temp=snapshot.cpu.temperature_c if snapshot.cpu else None,
        cpu_usage=snapshot.cpu.usage_percent if snapshot.cpu else None,
        ram_usage_pct=snapshot.memory.usage_percent if snapshot.memory else None,
        disk_temps=json.dumps(disk_temps),
        smart_status=json.dumps(smart_status),
        power_on_hours=json.dumps(poh),
        gpu_temp=gpu_temp,
        smart_attrs=json.dumps(attrs),
    )


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
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(telemetry)")}
            if "smart_attrs" not in columns:  # databases created before wear tracking
                conn.execute("ALTER TABLE telemetry ADD COLUMN smart_attrs TEXT DEFAULT '{}'")
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

    def record(self, snapshot: SystemSnapshot, machine_id: str = "", min_interval: float = 0) -> bool:
        """Save a telemetry snapshot. Returns ``False`` if skipped because the previous record
        for this machine is younger than *min_interval* seconds (repeated scans add no information)."""
        machine_id = machine_id or self.machine_id(snapshot)
        r = snapshot_to_record(snapshot)
        with self._connect() as conn:
            if min_interval:
                last = conn.execute(
                    "SELECT MAX(timestamp) AS ts FROM telemetry WHERE machine_id = ?", (machine_id,),
                ).fetchone()["ts"]
                if last is not None and r.timestamp - last < min_interval:
                    return False
            conn.execute(
                """INSERT INTO telemetry
                   (timestamp, machine_id, cpu_temp, cpu_usage, ram_usage_pct,
                    disk_temps, smart_status, power_on_hours, gpu_temp, smart_attrs)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r.timestamp, machine_id, r.cpu_temp, r.cpu_usage, r.ram_usage_pct,
                 r.disk_temps, r.smart_status, r.power_on_hours, r.gpu_temp, r.smart_attrs),
            )
        log.info("Telemetry recorded for machine %s", machine_id)
        return True

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
    def machine_id(snapshot: SystemSnapshot) -> str:
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
            smart_attrs=row["smart_attrs"] or "",
        )
