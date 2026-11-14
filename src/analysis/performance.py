"""Performance analysis — identify bottlenecks and resource hogs."""

from dataclasses import dataclass, field

from src.core.i18n import t
from src.core.logger import get_logger
from src.diagnostics.collector import SystemSnapshot

log = get_logger("analysis.performance")

# Thresholds shared with the health dashboard (src/analysis/health.py)
CPU_TEMP_HIGH, CPU_TEMP_CRITICAL = 70, 85
CPU_LOAD_HIGH = 90
RAM_HIGH, RAM_CRITICAL = 75, 90
SWAP_HIGH = 50
DISK_TEMP_HIGH = 55
PARTITION_FULL = 90
GPU_TEMP_HIGH, GPU_TEMP_CRITICAL = 80, 90


@dataclass
class Bottleneck:
    component: str = ""  # cpu | memory | disk | gpu
    severity: str = "info"  # info | warning | critical
    description: str = ""
    recommendation: str = ""
    kind: str = ""  # machine-readable finding type, stable across languages and values
    target: str = ""  # device the finding is about, if any


@dataclass
class PerformanceReport:
    bottlenecks: list[Bottleneck] = field(default_factory=list)
    score: int = 100  # 0-100 overall performance score
    lang: str = "ru"

    @property
    def summary(self) -> str:
        if not self.bottlenecks:
            return t("perf.summary.ok", self.lang, score=self.score)
        critical = sum(1 for b in self.bottlenecks if b.severity == "critical")
        return t("perf.summary", self.lang, score=self.score, n=len(self.bottlenecks), critical=critical)

    def add(self, kind: str, component: str, severity: str, penalty: int, target: str = "", **fmt) -> None:
        self.bottlenecks.append(Bottleneck(
            component=component,
            severity=severity,
            description=t(f"perf.{kind}", self.lang, **fmt),
            recommendation=t(f"perf.{kind}.rec", self.lang),
            kind=kind,
            target=target,
        ))
        self.score -= penalty


def analyze(snapshot: SystemSnapshot, lang: str = "ru") -> PerformanceReport:
    """Analyze system snapshot for performance bottlenecks."""
    report = PerformanceReport(lang=lang)
    _check_cpu(snapshot, report)
    _check_memory(snapshot, report)
    _check_disk(snapshot, report)
    _check_gpu(snapshot, report)
    report.score = max(0, report.score)
    return report


def _check_cpu(snapshot: SystemSnapshot, report: PerformanceReport) -> None:
    cpu = snapshot.cpu
    if not cpu:
        return

    if cpu.usage_percent is not None and cpu.usage_percent > CPU_LOAD_HIGH:
        report.add("cpu_load", "cpu", "warning", 15, v=cpu.usage_percent)

    if cpu.temperature_c is not None and cpu.temperature_c > CPU_TEMP_CRITICAL:
        report.add("cpu_temp_critical", "cpu", "critical", 25, v=cpu.temperature_c)
    elif cpu.temperature_c is not None and cpu.temperature_c > CPU_TEMP_HIGH:
        report.add("cpu_temp_high", "cpu", "warning", 10, v=cpu.temperature_c)

    if cpu.cores_physical == 1:
        report.add("single_core", "cpu", "info", 5)


def _check_memory(snapshot: SystemSnapshot, report: PerformanceReport) -> None:
    mem = snapshot.memory
    if not mem:
        return

    if mem.usage_percent > RAM_CRITICAL:
        report.add("ram_critical", "memory", "critical", 20, v=mem.usage_percent, used=mem.used_mb, total=mem.total_mb)
    elif mem.usage_percent > RAM_HIGH:
        report.add("ram_high", "memory", "warning", 10, v=mem.usage_percent)

    if 0 < mem.total_mb < 4096:
        report.add("ram_small", "memory", "warning", 10, total=mem.total_mb)

    if mem.swap_used_mb > 0 and mem.swap_total_mb > 0:
        swap_pct = mem.swap_used_mb / mem.swap_total_mb * 100
        if swap_pct > SWAP_HIGH:
            report.add("swap", "memory", "warning", 10, v=swap_pct)


def _check_disk(snapshot: SystemSnapshot, report: PerformanceReport) -> None:
    if not snapshot.disk:
        return

    for d in snapshot.disk.devices:
        if d.smart_healthy is False:
            report.add("smart_failing", "disk", "critical", 30, target=d.device, model=d.model, device=d.device)

        if d.temperature_c is not None and d.temperature_c > DISK_TEMP_HIGH:
            report.add("disk_temp", "disk", "warning", 5, target=d.device, model=d.model, v=d.temperature_c)

        if d.type == "HDD":
            report.add("hdd_slow", "disk", "info", 5, target=d.device, model=d.model)

        for part in d.partitions:
            if part.usage_percent > PARTITION_FULL and part.size_mb > 1024:
                report.add(
                    "partition_full", "disk", "warning", 10,
                    target=part.device, device=part.device, v=part.usage_percent,
                )


def _check_gpu(snapshot: SystemSnapshot, report: PerformanceReport) -> None:
    if not snapshot.gpu:
        return

    for g in snapshot.gpu.devices:
        if g.temperature_c is not None and g.temperature_c > GPU_TEMP_CRITICAL:
            report.add("gpu_temp", "gpu", "critical", 15, target=g.name, model=g.name, v=g.temperature_c)
