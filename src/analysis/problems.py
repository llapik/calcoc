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
            category="performance" if b.component != "disk" else "hardware",
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
            if d.smart_healthy is False:
                report.problems.append(Problem(
                    id=next_id(),
                    title=f"Диск {d.model} неисправен (S.M.A.R.T.)",
                    description="S.M.A.R.T. тест провален — срочно сделайте резервную копию данных",
                    severity=Severity.CRITICAL,
                    category="hardware",
                ))
            # Check failing attributes
            for attr in d.smart_attrs:
                if attr.status == "failing":
                    report.problems.append(Problem(
                        id=next_id(),
                        title=f"Атрибут S.M.A.R.T. {attr.name} в критическом состоянии ({d.model})",
                        description=f"Значение: {attr.value}, порог: {attr.threshold}, raw: {attr.raw_value}",
                        severity=Severity.CRITICAL,
                        category="hardware",
                    ))

            # Check partition usage
            for part in d.partitions:
                if part.usage_percent > 95 and part.size_mb > 1024:
                    report.problems.append(Problem(
                        id=next_id(),
                        title=f"Раздел {part.device} почти полон ({part.usage_percent}%)",
                        description="Очистите временные файлы для освобождения места",
                        severity=Severity.WARNING,
                        category="software",
                        auto_fixable=True,
                        fix_action="clean_temp_files",
                    ))

    # --- Filesystem errors (check if fsck reports issues) ---
    if snapshot.disk:
        for d in snapshot.disk.devices:
            for part in d.partitions:
                if part.filesystem in ("ext4", "ext3", "ext2"):
                    report.problems.append(Problem(
                        id=next_id(),
                        title=f"Проверка файловой системы {part.device} ({part.filesystem})",
                        description="Рекомендуется запустить fsck для проверки целостности",
                        severity=Severity.INFO,
                        category="software",
                        auto_fixable=True,
                        fix_action="fix_filesystem",
                    ))

    # --- Malware scan ---
    if scan_path and malware.check_clamav_available():
        try:
            scan_result = malware.scan(scan_path)
            if scan_result.infected_files > 0:
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

    # Sort by severity (critical first)
    severity_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    report.problems.sort(key=lambda p: severity_order.get(p.severity, 99))

    return report
