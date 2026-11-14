"""Health report — the system snapshot and its problems arranged for the dashboard.

Everything the dashboard shows (statuses, meters, thresholds) is decided here so the web UI only
draws. Statuses use four reserved levels: ``good`` < ``warning`` < ``serious`` < ``critical``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

from src.analysis import performance as perf
from src.analysis.problems import Problem, Severity
from src.core.i18n import t
from src.diagnostics.collector import SystemSnapshot

_LEVELS = ("good", "warning", "serious", "critical")
_PENALTY = {Severity.CRITICAL: 30, Severity.WARNING: 8, Severity.INFO: 2}  # percent of the remaining score
_SEVERITY_STATUS = {Severity.CRITICAL: "critical", Severity.WARNING: "warning", Severity.INFO: "good"}


def worst(*statuses: str) -> str:
    return max((s for s in statuses if s in _LEVELS), key=_LEVELS.index, default="good")


def _level(value: float, warning: float, serious: float | None = None, critical: float | None = None) -> str:
    if critical is not None and value > critical:
        return "critical"
    if serious is not None and value > serious:
        return "serious"
    return "warning" if value > warning else "good"


@dataclass
class Meter:
    """One ratio against a limit, drawn as a bar."""
    label: str
    text: str            # value as shown, with unit
    percent: float       # bar fill, 0-100
    status: str = "good"


@dataclass
class Component:
    id: str
    kind: str                       # cpu | memory | disk | gpu | board | os | network | security
    title: str                      # "Processor"
    name: str = ""                  # model / product
    status: str = "good"
    meters: list[Meter] = field(default_factory=list)
    facts: list[tuple[str, str]] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)
    table: dict | None = None       # optional detail table: {"columns": [...], "rows": [[...]], "row_status": [...]}


@dataclass
class HealthReport:
    score: int
    status: str
    verdict: str
    counts: dict
    components: list[Component]

    def to_dict(self) -> dict:
        return asdict(self)


def build(snapshot: SystemSnapshot, problems: list[Problem], lang: str = "ru") -> HealthReport:
    """Build the dashboard model from a snapshot and its *open* problems."""
    def tr(key: str, **fmt) -> str:
        return t(f"health.{key}", lang, **fmt)

    components: list[Component] = []

    # --- CPU ---
    if cpu := snapshot.cpu:
        c = Component("cpu", "cpu", tr("cpu"), cpu.model)
        if cpu.temperature_c is not None:
            c.meters.append(Meter(
                tr("m.temp"), f"{cpu.temperature_c:.0f} °C", min(cpu.temperature_c, 100),
                _level(cpu.temperature_c, perf.CPU_TEMP_HIGH, critical=perf.CPU_TEMP_CRITICAL),
            ))
        if cpu.usage_percent is not None:
            c.meters.append(Meter(
                tr("m.load"), f"{cpu.usage_percent:.0f}%", cpu.usage_percent,
                _level(cpu.usage_percent, perf.CPU_LOAD_HIGH),
            ))
        c.facts.append((tr("f.cores"), f"{cpu.cores_physical} / {cpu.cores_logical}"))
        if cpu.frequency_mhz:
            c.facts.append((
                tr("f.freq"),
                tr("f.freq.value", cur=cpu.frequency_mhz, max=cpu.frequency_max_mhz or cpu.frequency_mhz),
            ))
        components.append(c)

    # --- Memory ---
    if (mem := snapshot.memory) and mem.total_mb:
        c = Component("memory", "memory", tr("memory"), _size(mem.total_mb, tr))
        c.meters.append(Meter(
            tr("m.used"), f"{mem.usage_percent:.0f}% · {_size(mem.used_mb, tr)}", mem.usage_percent,
            _level(mem.usage_percent, perf.RAM_HIGH, serious=perf.RAM_CRITICAL),
        ))
        if mem.swap_total_mb:
            swap = mem.swap_used_mb / mem.swap_total_mb * 100
            c.meters.append(Meter(tr("m.swap"), f"{swap:.0f}%", swap, _level(swap, perf.SWAP_HIGH)))
        if mem.slots:
            modules = ", ".join(f"{_size(s.size_mb, tr)} {s.type}" for s in mem.slots)
            c.facts.append((tr("f.modules"), modules))
            c.name = f"{_size(mem.total_mb, tr)} {mem.slots[0].type}"
        if mem.max_capacity_mb:
            c.facts.append((tr("f.max"), _size(mem.max_capacity_mb, tr)))
        components.append(c)

    # --- Disks: one card per device ---
    for d in (snapshot.disk.devices if snapshot.disk else []):
        c = Component(f"disk:{d.device}", "disk", tr("disk"), d.model)
        if d.smart_healthy is False:
            c.status = "critical"
        smart = "smart.ok" if d.smart_healthy else ("smart.fail" if d.smart_healthy is False else "smart.unknown")
        c.facts.append((tr("f.type"), f"{d.type} · {d.size_gb:.0f} {tr('unit.gb')}"))
        c.facts.append((tr("f.smart"), tr(smart)))
        if d.power_on_hours is not None:
            c.facts.append((tr("f.hours"), tr("f.hours.value", h=d.power_on_hours, y=d.power_on_hours / 8766)))
        if d.temperature_c is not None:
            c.meters.append(Meter(
                tr("m.temp"), f"{d.temperature_c} °C", min(d.temperature_c / 70 * 100, 100),
                _level(d.temperature_c, perf.DISK_TEMP_HIGH, serious=65),
            ))
        for part in d.partitions:
            if part.size_mb > 1024 and part.used_mb:
                c.meters.append(Meter(
                    tr("partition", device=part.mount_point or part.device),
                    f"{part.usage_percent:.0f}% · {_size(part.size_mb, tr)}", part.usage_percent,
                    _level(part.usage_percent, perf.PARTITION_FULL, serious=97),
                ))
        if d.smart_attrs:
            c.table = {
                "columns": ["ID", "Attribute", "Value", "Worst", "Threshold", "Raw"],
                "rows": [[a.id, a.name, a.value, a.worst, a.threshold, a.raw_value] for a in d.smart_attrs],
                "row_status": [{"failing": "critical", "warning": "warning"}.get(a.status, "good")
                               for a in d.smart_attrs],
            }
        components.append(c)

    # --- GPU ---
    for i, g in enumerate(snapshot.gpu.devices if snapshot.gpu else []):
        c = Component(f"gpu:{i}", "gpu", tr("gpu"), g.name)
        if g.temperature_c is not None:
            c.meters.append(Meter(
                tr("m.temp"), f"{g.temperature_c} °C", min(g.temperature_c, 100),
                _level(g.temperature_c, perf.GPU_TEMP_HIGH, critical=perf.GPU_TEMP_CRITICAL),
            ))
        if g.vram_mb:
            c.facts.append((tr("f.vram"), _size(g.vram_mb, tr)))
        if g.driver and g.driver != "Unknown":
            c.facts.append((tr("f.driver"), g.driver))
        components.append(c)

    # --- OS ---
    if os_info := snapshot.os:
        names = [(o.version if o.name == "Windows" else o.name) or o.name for o in os_info.detected]
        c = Component("os", "os", tr("os"), ", ".join(names) or tr("f.os_none"))
        c.facts.append((tr("f.boot"), os_info.boot_mode))
        components.append(c)

    # --- Security: shown once anything was checked or found ---
    threats = [p for p in problems if p.component == "security"]
    if threats:
        components.append(Component(
            "security", "security", tr("security"), tr("security.threats", n=len(threats)),
        ))

    # --- Board ---
    if mb := snapshot.motherboard:
        c = Component("board", "board", tr("board"), f"{mb.manufacturer} {mb.product_name}".strip())
        c.facts.append((tr("f.bios"), f"{mb.bios_version} ({mb.bios_date})" if mb.bios_date else mb.bios_version))
        c.facts.append((tr("f.chassis"), mb.chassis_type))
        components.append(c)

    # --- Network ---
    if net := snapshot.network:
        up = [i for i in net.interfaces if i.state == "up"]
        c = Component("network", "network", tr("network"), ", ".join(i.name for i in up) or "—")
        c.facts.append((tr("f.internet"), tr("yes") if net.internet_available else tr("no")))
        if net.gateway:
            c.facts.append((tr("f.gateway"), net.gateway))
        components.append(c)

    _attach_problems(components, problems)
    for c in components:
        c.status = worst(c.status, *(m.status for m in c.meters), *(p["status"] for p in c.problems))

    # Each problem takes a share of what is left, so the score keeps telling systems apart
    # instead of bottoming out at zero after four findings.
    remaining = 1.0
    for p in problems:
        remaining *= 1 - _PENALTY[p.severity] / 100
    score = round(100 * remaining)
    status = "good" if score >= 85 else "warning" if score >= 65 else "serious" if score >= 40 else "critical"
    if any(p.severity == Severity.CRITICAL for p in problems):
        status = worst(status, "serious")  # a critical finding is never "a few things need attention"
    return HealthReport(
        score=score,
        status=status,
        verdict=tr(f"verdict.{status}"),
        counts={
            "critical": sum(1 for p in problems if p.severity == Severity.CRITICAL),
            "warning": sum(1 for p in problems if p.severity == Severity.WARNING),
            "info": sum(1 for p in problems if p.severity == Severity.INFO),
            "fixable": sum(1 for p in problems if p.auto_fixable),
        },
        components=components,
    )


def _attach_problems(components: list[Component], problems: list[Problem]) -> None:
    by_id = {c.id: c for c in components}
    by_kind: dict[str, Component] = {}
    for c in components:
        by_kind.setdefault(c.kind, c)
    for p in problems:
        kind = p.component or "os"
        card = by_id.get(f"{kind}:{p.target}") or by_kind.get(kind)
        if card is None and kind == "gpu":
            card = next((c for c in components if c.kind == "gpu" and c.name == p.target), None)
        if card is None:
            card = by_kind.get("os")
        if card is not None:
            card.problems.append({
                "key": p.key, "title": p.title, "severity": p.severity.value,
                "status": _SEVERITY_STATUS[p.severity], "fixable": p.auto_fixable,
            })


def _size(mb: float, tr) -> str:
    if mb >= 1024:
        gb = mb / 1024
        return f"{gb:.0f} {tr('unit.gb')}" if abs(gb - round(gb)) < 0.05 or gb >= 100 else f"{gb:.1f} {tr('unit.gb')}"
    return f"{mb:.0f} {tr('unit.mb')}"
