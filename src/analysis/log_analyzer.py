"""Analyze system logs for errors and anomalies."""

import os
import re
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("analysis.logs")

# Patterns indicating problems
_ERROR_PATTERNS = [
    (re.compile(r"(kernel panic|BUG:|Oops:|segfault)", re.IGNORECASE), "critical"),
    (re.compile(r"(out of memory|oom-killer|OOM)", re.IGNORECASE), "critical"),
    (re.compile(r"(I/O error|medium error|read error|write error)", re.IGNORECASE), "critical"),
    (re.compile(r"(hardware error|machine check|MCE)", re.IGNORECASE), "critical"),
    (re.compile(r"(BSOD|blue screen|bug check)", re.IGNORECASE), "critical"),
    (re.compile(r"(failed|failure|error|corrupt)", re.IGNORECASE), "warning"),
    (re.compile(r"(temperature above threshold|overheating)", re.IGNORECASE), "warning"),
    (re.compile(r"(deprecated|obsolete)", re.IGNORECASE), "info"),
]

# Linux log files to check
_LINUX_LOGS = [
    "/var/log/syslog",
    "/var/log/messages",
    "/var/log/kern.log",
    "/var/log/dmesg",
    "/var/log/Xorg.0.log",
]

# Windows event log paths (when NTFS is mounted)
_WINDOWS_LOGS = [
    "Windows/System32/winevt/Logs/System.evtx",
    "Windows/System32/winevt/Logs/Application.evtx",
]


@dataclass
class LogEntry:
    source: str = ""
    line_number: int = 0
    text: str = ""
    severity: str = "info"  # info | warning | critical


@dataclass
class LogAnalysisResult:
    entries: list[LogEntry] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    sources_analyzed: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"Проанализировано источников: {len(self.sources_analyzed)}, "
            f"критических: {self.critical_count}, предупреждений: {self.warning_count}"
        )


def analyze(mount_points: list[str] | None = None) -> LogAnalysisResult:
    """Analyze system logs from Linux paths and mounted Windows partitions."""
    result = LogAnalysisResult()

    # Analyze Linux logs
    for log_path in _LINUX_LOGS:
        if os.path.isfile(log_path):
            _analyze_text_log(log_path, result)

    # Analyze dmesg ring buffer directly
    _analyze_dmesg(result)

    # Look for Windows logs on mounted partitions
    if mount_points:
        for mp in mount_points:
            for wlog in _WINDOWS_LOGS:
                full = os.path.join(mp, wlog)
                if os.path.isfile(full):
                    result.sources_analyzed.append(full)
                    # Note: EVTX parsing requires python-evtx; basic detection only
                    log.info("Windows event log found: %s (EVTX parsing not yet implemented)", full)

    result.critical_count = sum(1 for e in result.entries if e.severity == "critical")
    result.warning_count = sum(1 for e in result.entries if e.severity == "warning")
    return result


def _analyze_text_log(path: str, result: LogAnalysisResult, max_lines: int = 5000) -> None:
    """Scan last *max_lines* of a text-based log for error patterns."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except Exception as exc:
        log.debug("Cannot read %s: %s", path, exc)
        return

    result.sources_analyzed.append(path)
    tail = lines[-max_lines:] if len(lines) > max_lines else lines
    offset = max(0, len(lines) - max_lines)

    for i, line in enumerate(tail):
        for pattern, severity in _ERROR_PATTERNS:
            if pattern.search(line):
                result.entries.append(
                    LogEntry(
                        source=path,
                        line_number=offset + i + 1,
                        text=line.strip()[:300],
                        severity=severity,
                    )
                )
                break  # one match per line


def _analyze_dmesg(result: LogAnalysisResult) -> None:
    """Read kernel ring buffer."""
    import subprocess

    try:
        output = subprocess.check_output(
            ["dmesg", "--level=err,crit,alert,emerg"],
            text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return

    result.sources_analyzed.append("dmesg")
    for i, line in enumerate(output.strip().splitlines()[:500]):
        for pattern, severity in _ERROR_PATTERNS:
            if pattern.search(line):
                result.entries.append(
                    LogEntry(source="dmesg", line_number=i + 1, text=line.strip()[:300], severity=severity)
                )
                break
