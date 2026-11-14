"""Demo scenarios — canned "sick PCs" that exercise the whole pipeline without real hardware.

A scenario is a JSON file in ``data/demo``: a system snapshot, extra problems the snapshot alone
cannot express (log errors, malware, a broken bootloader) and a description of sandbox files.
Repairs in demo mode act on that sandbox directory only, so cleanup, quarantine, backup and
rollback are all real file operations — just never on the user's system.
"""

from __future__ import annotations

import copy
import json
import shutil
import types
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from src.analysis.problems import Problem, Severity
from src.core.i18n import pick
from src.core.logger import get_logger
from src.diagnostics.collector import SystemSnapshot
from src.telemetry.collector import TelemetryRecord

log = get_logger("demo")

_HARMLESS = "calcoc demo sample: harmless placeholder standing in for an infected file\n"


def from_dict(cls: type, data: dict | None) -> Any:
    """Build dataclass *cls* (with nested dataclasses and lists) from plain dicts."""
    if data is None:
        return None
    hints = get_type_hints(cls)
    return cls(**{
        f.name: _convert(hints[f.name], data[f.name])
        for f in fields(cls) if f.name in data
    })


def _convert(tp: Any, value: Any) -> Any:
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        if value is None:
            return None
        return _convert(next(a for a in get_args(tp) if a is not type(None)), value)
    if origin is list:
        return [_convert(get_args(tp)[0], v) for v in value]
    if is_dataclass(tp):
        return from_dict(tp, value)
    return value


def _set_path(data: Any, dotted: str, value: Any) -> None:
    """Assign ``value`` at ``a.b.0.c`` inside nested dicts/lists."""
    *parents, last = dotted.split(".")
    for part in parents:
        data = data[int(part)] if isinstance(data, list) else data[part]
    if isinstance(data, list):
        data[int(last)] = value
    else:
        data[last] = value


def list_scenarios(demo_dir: Path, lang: str = "ru") -> list[dict]:
    result = []
    for path in sorted(demo_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Bad demo scenario %s: %s", path.name, exc)
            continue
        result.append({
            "id": path.stem,
            "title": pick(raw.get("title"), lang),
            "description": pick(raw.get("description"), lang),
        })
    return result


class DemoSession:
    """One loaded scenario plus the set of problems already fixed in it."""

    def __init__(self, demo_dir: Path, scenario_id: str, sandbox_root: Path):
        path = demo_dir / f"{scenario_id}.json"
        if not scenario_id.replace("_", "").isalnum() or not path.is_file():
            raise KeyError(scenario_id)
        self.id = scenario_id
        self._raw: dict = json.loads(path.read_text(encoding="utf-8"))
        self.sandbox = sandbox_root / scenario_id
        self.fixed: set[str] = set()
        self._prepare_sandbox()

    def title(self, lang: str) -> str:
        return pick(self._raw.get("title"), lang)

    # ------------------------------------------------------------------
    # State derived from "pristine scenario + fixes applied so far"
    # ------------------------------------------------------------------
    def snapshot(self) -> SystemSnapshot:
        data = copy.deepcopy(self._raw["snapshot"])
        for key in self.fixed:
            for patch in self._raw.get("on_fix", {}).get(key, []):
                _set_path(data, patch["path"], patch["value"])
        return from_dict(SystemSnapshot, data)

    def problems(self, lang: str) -> list[Problem]:
        result = []
        for raw in self._raw.get("problems", []):
            if raw["key"] in self.fixed:
                continue
            action = raw.get("fix_action", "")
            params: dict = {}
            if files := raw.get("files"):
                params["files"] = [str(self.sandbox / f) for f in files]
            result.append(Problem(
                key=raw["key"],
                title=pick(raw.get("title"), lang),
                description=pick(raw.get("description"), lang),
                severity=Severity(raw.get("severity", "warning")),
                category=raw.get("category", "software"),
                auto_fixable=bool(action),
                fix_action=action,
                fix_params=params,
                component=raw.get("component", ""),
                target=raw.get("target", ""),
            ))
        return result

    def history(self, now: float) -> list[TelemetryRecord]:
        """The scenario's past measurements, oldest first (the present comes from :meth:`snapshot`)."""
        records = []
        for h in sorted(self._raw.get("history", []), key=lambda h: -h["days_ago"]):
            disks: dict = h.get("disks", {})
            records.append(TelemetryRecord(
                timestamp=now - h["days_ago"] * 86400,
                machine_id=f"demo:{self.id}",
                cpu_temp=h.get("cpu_temp"),
                cpu_usage=h.get("cpu_usage"),
                ram_usage_pct=h.get("ram"),
                gpu_temp=h.get("gpu_temp"),
                disk_temps=json.dumps({dev: d["temp"] for dev, d in disks.items() if "temp" in d}),
                smart_status=json.dumps({dev: d["healthy"] for dev, d in disks.items() if "healthy" in d}),
                power_on_hours=json.dumps({dev: d["hours"] for dev, d in disks.items() if "hours" in d}),
                smart_attrs=json.dumps({
                    dev: {attr: d[name] for attr, name in (("5", "realloc"), ("197", "pending")) if name in d}
                    for dev, d in disks.items()
                }),
            ))
        return records

    def cleanup_dirs(self) -> list[str]:
        """Sandbox directories that stand in for the scenario's temp folders."""
        junk = self.sandbox / "junk"
        return [str(junk)] if junk.is_dir() else []

    def marker_file(self, action: str) -> Path:
        """File a simulated repair "modifies", so backup and rollback have something real to do."""
        marker = self.sandbox / "state" / f"{action}.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        if not marker.exists():
            marker.write_text(json.dumps({"action": action, "repaired": False}), encoding="utf-8")
        return marker

    # ------------------------------------------------------------------
    def _prepare_sandbox(self) -> None:
        if self.sandbox.exists():
            shutil.rmtree(self.sandbox)
        self.sandbox.mkdir(parents=True)
        spec = self._raw.get("sandbox", {})
        for item in spec.get("junk", []):
            target = self.sandbox / "junk" / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\0" * (int(item.get("size_kb", 16)) * 1024))
        for raw in self._raw.get("problems", []):
            for rel in raw.get("files", []):
                target = self.sandbox / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_HARMLESS, encoding="utf-8")
