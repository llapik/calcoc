"""Problem classification — aggregate findings from all analysis modules."""

from dataclasses import dataclass, field
from enum import Enum

from src.core.i18n import t
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
    key: str = ""  # stable identity across re-analysis (id is only a display number)
    fix_params: dict = field(default_factory=dict)  # server-side arguments for the repair handler
    component: str = ""  # cpu | memory | disk | gpu | os | network | security — for the health dashboard
    target: str = ""  # device the problem is about (e.g. /dev/sda), if any


@dataclass
class ProblemReport:
    problems: list[Problem] = field(default_factory=list)
    lang: str = "ru"

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
            return t("problems.none", self.lang)
        return t(
            "problems.summary", self.lang,
            total=total, critical=self.critical_count, fixable=self.fixable_count,
        )


def analyze_all(
    snapshot: SystemSnapshot,
    mount_points: list[str] | None = None,
    scan_path: str | None = None,
    host_checks: bool = True,
    extra: list[Problem] | None = None,
    lang: str = "ru",
) -> ProblemReport:
    """Run all analysis modules and compile a unified problem report.

    ``host_checks=False`` skips everything that inspects the machine we run on (logs, ClamAV) —
    used when *snapshot* describes another system, e.g. a demo scenario. ``extra`` problems are
    appended as-is.
    """
    report = ProblemReport(lang=lang)
    add = report.problems.append

    # --- Performance analysis ---
    for b in performance.analyze(snapshot, lang).bottlenecks:
        if b.kind in ("smart_failing", "partition_full"):
            continue  # reported below with more detail and a fix action
        add(Problem(
            key=f"perf:{b.kind}:{b.target}",
            title=b.description,
            description=b.recommendation,
            severity=Severity(b.severity),
            category="hardware" if b.component == "disk" else "performance",
            component=b.component,
            target=b.target,
        ))

    # --- Log analysis ---
    try:
        log_result = log_analyzer.analyze(mount_points=mount_points) if host_checks else None
        if log_result and log_result.critical_count > 0:
            sample = "; ".join(e.text[:120] for e in log_result.entries if e.severity == "critical")[:400]
            add(Problem(
                key="logs:critical",
                title=t("problem.logs_critical", lang, n=log_result.critical_count),
                description=t(
                    "problem.logs_critical.desc", lang,
                    sources=len(log_result.sources_analyzed), sample=sample,
                ),
                severity=Severity.CRITICAL,
                category="software",
                component="os",
            ))
        if log_result and log_result.warning_count > 5:
            add(Problem(
                key="logs:warnings",
                title=t("problem.logs_warnings", lang, n=log_result.warning_count),
                description=t("problem.logs_warnings.desc", lang),
                severity=Severity.WARNING,
                category="software",
                component="os",
            ))
    except Exception as exc:
        log.warning("Log analysis failed: %s", exc)

    # --- Disk health ---
    if snapshot.disk:
        for d in snapshot.disk.devices:
            # Overall S.M.A.R.T. failure
            if d.smart_healthy is False:
                add(Problem(
                    key=f"smart_failing:{d.device}",
                    title=t("problem.smart_failing", lang, model=d.model),
                    description=t("problem.smart_failing.desc", lang),
                    severity=Severity.CRITICAL,
                    category="hardware",
                    component="disk",
                    target=d.device,
                ))

            # Individual failing SMART attributes
            for attr in d.smart_attrs:
                if attr.status == "failing":
                    add(Problem(
                        key=f"smart_attr:{d.device}:{attr.id}",
                        title=t("problem.smart_attr", lang, name=attr.name, model=d.model),
                        description=t(
                            "problem.smart_attr.desc", lang,
                            value=attr.value, threshold=attr.threshold, raw=attr.raw_value,
                        ),
                        severity=Severity.CRITICAL,
                        category="hardware",
                        component="disk",
                        target=d.device,
                    ))

            # Partition almost full (>90 %, >1 GB)
            for part in d.partitions:
                if part.usage_percent > performance.PARTITION_FULL and part.size_mb > 1024:
                    add(Problem(
                        key=f"partition_full:{part.device}",
                        fix_params={"device": part.device, "mount_point": part.mount_point},
                        title=t("problem.partition_full", lang, device=part.device, v=part.usage_percent),
                        description=t("problem.partition_full.desc", lang),
                        severity=Severity.WARNING,
                        category="software",
                        auto_fixable=True,
                        fix_action="clean_temp_files",
                        component="disk",
                        target=d.device,
                    ))

    # --- Malware scan (only when explicitly requested) ---
    if host_checks and scan_path and malware.check_clamav_available():
        try:
            scan_result = malware.scan(scan_path)
            for hit in scan_result.hits[:20]:
                add(Problem(
                    key=f"malware:{hit.file_path}",
                    fix_params={"files": [hit.file_path]},
                    title=t("problem.malware", lang, signature=hit.signature),
                    description=t("problem.malware.desc", lang, path=hit.file_path),
                    severity=Severity.CRITICAL,
                    category="security",
                    auto_fixable=True,
                    fix_action="remove_malware",
                    component="security",
                ))
        except Exception as exc:
            log.warning("Malware scan failed: %s", exc)

    report.problems.extend(extra or [])

    # Sort: critical → warning → info, then number in display order
    report.problems.sort(key=lambda p: _SEVERITY_ORDER.get(p.severity, 99))
    for n, p in enumerate(report.problems, start=1):
        p.id = f"P{n:03d}"

    return report
