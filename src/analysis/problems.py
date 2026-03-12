"""Problem classification — aggregate findings from all analysis modules."""

from dataclasses import dataclass, field
from enum import Enum

from src.core.logger import get_logger
from src.diagnostics.collector import SystemSnapshot
from src.analysis import log_analyzer, performance, malware

log = get_logger("analysis.problems")


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2,
}


@dataclass
class Problem:
    id: str = ""
    title: str = ""
    description: str = ""
    severity: Severity = Severity.INFO
    category: str = ""  # hardware | software | security | performance
    auto_fixable: bool = False
    fix_action: str = ""  # action key from safety_rules.yaml


@dataclass
class ProblemReport:
    problems: list[Problem] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for p in self.problems if p.severity == Severity.CRITICAL)

    @property
    def fixable_count(self) -> int:
        return sum(1 for p in self.problems if p.auto_fixable)

    @property
    def summary(self) -> str:
        total = len(self.problems)
        if total == 0:
            return "Проблем не обнаружено"
        return (
            f"Обнаружено проблем: {total} "
            f"(критических: {self.critical_count}, "
            f"автоисправимых: {self.fixable_count})"
        )


def analyze_all(
    snapshot: SystemSnapshot,
    mount_points: list[str] | None = None,
    scan_path: str | None = None,
) -> ProblemReport:
    """Run all analysis modules and compile a unified problem report."""
    report = ProblemReport()
    _id = 0

    def next_id() -> str:
        nonlocal _id
        _id += 1
        return f"P{_id:03d}"

    # --- Performance analysis ---
    perf = performance.analyze(snapshot)
    for b in perf.bottlenecks:
        report.problems.append(Problem(
            id=next_id(),
            title=b.description,
            description=b.recommendation,
            severity=Severity(b.severity),
            category="hardware" if b.component == "disk" else "performance",
            auto_fixable=False,
        ))

    # --- Log analysis ---
    try:
        log_result = log_analyzer.analyze(mount_points=mount_points)
        if log_result.critical_count > 0:
            report.problems.append(Problem(
                id=next_id(),
                title=f"Найдено {log_result.critical_count} критических записей в логах",
                description=log_result.summary,
                severity=Severity.CRITICAL,
                category="software",
            ))
        if log_result.warning_count > 5:
            report.problems.append(Problem(
                id=next_id(),
                title=f"Найдено {log_result.warning_count} предупреждений в логах",
                description="Рекомендуется детальный анализ системных логов",
                severity=Severity.WARNING,
                category="software",
            ))
    except Exception as exc:
        log.warning("Log analysis failed: %s", exc)

    # --- Disk health ---
    if snapshot.disk:
        for d in snapshot.disk.devices:
            # Overall S.M.A.R.T. failure
            if d.smart_healthy is False:
                report.problems.append(Problem(
                    id=next_id(),
                    title=f"Диск {d.model} неисправен (S.M.A.R.T.)",
                    description="S.M.A.R.T. тест провален — срочно сделайте резервную копию данных!",
                    severity=Severity.CRITICAL,
                    category="hardware",
                ))

            # Individual failing SMART attributes
            for attr in d.smart_attrs:
                if attr.status == "failing":
                    report.problems.append(Problem(
                        id=next_id(),
                        title=f"S.M.A.R.T. атрибут {attr.name} критический ({d.model})",
                        description=(
                            f"Значение: {attr.value}, порог: {attr.threshold}, "
                            f"raw: {attr.raw_value}"
                        ),
                        severity=Severity.CRITICAL,
                        category="hardware",
                    ))

            # Partition almost full (>95 %, >1 GB)
            for part in d.partitions:
                if part.usage_percent > 95 and part.size_mb > 1024:
                    report.problems.append(Problem(
                        id=next_id(),
                        title=f"Раздел {part.device} почти полон ({part.usage_percent:.0f}%)",
                        description="Очистите временные файлы для освобождения места",
                        severity=Severity.WARNING,
                        category="software",
                        auto_fixable=True,
                        fix_action="clean_temp_files",
                    ))

    # --- Malware scan (only when explicitly requested) ---
    if scan_path and malware.check_clamav_available():
        try:
            scan_result = malware.scan(scan_path)
            for hit in scan_result.hits[:20]:
                report.problems.append(Problem(
                    id=next_id(),
                    title=f"Обнаружено вредоносное ПО: {hit.signature}",
                    description=f"Файл: {hit.file_path}",
                    severity=Severity.CRITICAL,
                    category="security",
                    auto_fixable=True,
                    fix_action="remove_malware",
                ))
        except Exception as exc:
            log.warning("Malware scan failed: %s", exc)

    # Sort: critical → warning → info
    report.problems.sort(key=lambda p: _SEVERITY_ORDER.get(p.severity, 99))

    return report
