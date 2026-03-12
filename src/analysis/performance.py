"""Performance analysis — identify bottlenecks and resource hogs."""

from dataclasses import dataclass, field

from src.core.logger import get_logger
from src.diagnostics.collector import SystemSnapshot

log = get_logger("analysis.performance")


@dataclass
class Bottleneck:
    component: str = ""  # cpu | ram | disk | gpu
    severity: str = "info"  # info | warning | critical
    description: str = ""
    recommendation: str = ""


@dataclass
class PerformanceReport:
    bottlenecks: list[Bottleneck] = field(default_factory=list)
    score: int = 100  # 0-100 overall health score

    @property
    def summary(self) -> str:
        if not self.bottlenecks:
            return f"Оценка производительности: {self.score}/100 — проблем не обнаружено"
        critical = sum(1 for b in self.bottlenecks if b.severity == "critical")
        return (
            f"Оценка производительности: {self.score}/100 — "
            f"найдено узких мест: {len(self.bottlenecks)} (критических: {critical})"
        )


def analyze(snapshot: SystemSnapshot) -> PerformanceReport:
    """Analyze system snapshot for performance bottlenecks."""
    report = PerformanceReport()
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

    if cpu.usage_percent is not None and cpu.usage_percent > 90:
        report.bottlenecks.append(Bottleneck(
            component="cpu",
            severity="warning",
            description=f"Загрузка CPU: {cpu.usage_percent}%",
            recommendation="Проверьте запущенные процессы, возможно есть зависшие приложения",
        ))
        report.score -= 15

    if cpu.temperature_c is not None and cpu.temperature_c > 85:
        report.bottlenecks.append(Bottleneck(
            component="cpu",
            severity="critical",
            description=f"Температура CPU: {cpu.temperature_c}°C (критически высокая)",
            recommendation="Проверьте систему охлаждения: термопасту, вентиляторы, радиатор",
        ))
        report.score -= 25
    elif cpu.temperature_c is not None and cpu.temperature_c > 70:
        report.bottlenecks.append(Bottleneck(
            component="cpu",
            severity="warning",
            description=f"Температура CPU: {cpu.temperature_c}°C (повышенная)",
            recommendation="Рекомендуется очистка системы охлаждения",
        ))
        report.score -= 10

    if cpu.cores_physical == 1:
        report.bottlenecks.append(Bottleneck(
            component="cpu",
            severity="info",
            description="Одноядерный процессор — ограниченная многозадачность",
            recommendation="Рассмотрите апгрейд на многоядерный процессор",
        ))
        report.score -= 5


def _check_memory(snapshot: SystemSnapshot, report: PerformanceReport) -> None:
    mem = snapshot.memory
    if not mem:
        return

    if mem.usage_percent > 90:
        report.bottlenecks.append(Bottleneck(
            component="ram",
            severity="critical",
            description=f"ОЗУ загружена на {mem.usage_percent}% ({mem.used_mb}/{mem.total_mb} МБ)",
            recommendation="Закройте неиспользуемые приложения или увеличьте объём ОЗУ",
        ))
        report.score -= 20
    elif mem.usage_percent > 75:
        report.bottlenecks.append(Bottleneck(
            component="ram",
            severity="warning",
            description=f"ОЗУ загружена на {mem.usage_percent}%",
            recommendation="Рассмотрите увеличение объёма ОЗУ",
        ))
        report.score -= 10

    if mem.total_mb < 4096:
        report.bottlenecks.append(Bottleneck(
            component="ram",
            severity="warning",
            description=f"Малый объём ОЗУ: {mem.total_mb} МБ",
            recommendation="Для комфортной работы рекомендуется минимум 8 ГБ ОЗУ",
        ))
        report.score -= 10

    if mem.swap_used_mb > 0 and mem.swap_total_mb > 0:
        swap_pct = mem.swap_used_mb / mem.swap_total_mb * 100
        if swap_pct > 50:
            report.bottlenecks.append(Bottleneck(
                component="ram",
                severity="warning",
                description=f"Активное использование SWAP ({swap_pct:.0f}%)",
                recommendation="Система использует подкачку — добавьте ОЗУ для ускорения",
            ))
            report.score -= 10


def _check_disk(snapshot: SystemSnapshot, report: PerformanceReport) -> None:
    if not snapshot.disk:
        return

    for d in snapshot.disk.devices:
        if d.smart_healthy is False:
            report.bottlenecks.append(Bottleneck(
                component="disk",
                severity="critical",
                description=f"Диск {d.model} ({d.device}) — S.M.A.R.T. FAILING",
                recommendation="СРОЧНО сделайте резервную копию данных! Диск может выйти из строя",
            ))
            report.score -= 30

        if d.temperature_c is not None and d.temperature_c > 55:
            report.bottlenecks.append(Bottleneck(
                component="disk",
                severity="warning",
                description=f"Температура диска {d.model}: {d.temperature_c}°C",
                recommendation="Проверьте вентиляцию корпуса",
            ))
            report.score -= 5

        if d.type == "HDD":
            report.bottlenecks.append(Bottleneck(
                component="disk",
                severity="info",
                description=f"HDD-диск {d.model} — медленнее SSD",
                recommendation="Замена на SSD значительно ускорит загрузку и работу системы",
            ))
            report.score -= 5

        # Check partition usage
        for part in d.partitions:
            if part.usage_percent > 90 and part.size_mb > 1024:
                report.bottlenecks.append(Bottleneck(
                    component="disk",
                    severity="warning",
                    description=f"Раздел {part.device} заполнен на {part.usage_percent}%",
                    recommendation="Освободите место — очистите временные файлы или переместите данные",
                ))
                report.score -= 10


def _check_gpu(snapshot: SystemSnapshot, report: PerformanceReport) -> None:
    if not snapshot.gpu:
        return

    for g in snapshot.gpu.devices:
        if g.temperature_c is not None and g.temperature_c > 90:
            report.bottlenecks.append(Bottleneck(
                component="gpu",
                severity="critical",
                description=f"Температура GPU {g.name}: {g.temperature_c}°C",
                recommendation="Проверьте охлаждение видеокарты",
            ))
            report.score -= 15
