"""Repair executor — the single path every modification takes.

``safety check → confirmation → backup → action → journal``. Nothing in the web layer or the AI
calls a repair module directly; they call :meth:`RepairExecutor.execute` and get a
:class:`RepairOutcome` describing what happened.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.core import platform
from src.core.config import Config
from src.core.i18n import t
from src.core.logger import get_logger
from src.rollback.backup import BackupInfo, BackupManager
from src.rollback.journal import Journal
from src.safety.classifier import SafetyClassifier, SafetyVerdict

if TYPE_CHECKING:
    from src.demo.scenarios import DemoSession

log = get_logger("repair.executor")

# Outcome statuses
DONE = "done"
BLOCKED = "blocked"                      # safety rules forbid it at the current permission level
NEEDS_CONFIRMATION = "needs_confirmation"
UNAVAILABLE = "unavailable"              # cannot be done in this run mode (e.g. needs the USB stick)
FAILED = "failed"


@dataclass
class RepairOutcome:
    status: str
    action: str
    message: str = ""
    risk_level: str = ""
    risk_label: str = ""
    requires_confirmation: bool = False
    requires_backup: bool = False
    plan: str = ""                 # what will be / was done, in plain words
    journal_id: int | None = None
    can_rollback: bool = False
    simulated: bool = False
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == DONE

    def to_dict(self) -> dict:
        return asdict(self) | {"ok": self.ok}


@dataclass
class _Work:
    """What a handler returns: the backup that makes the change undoable plus a user message."""
    backup: BackupInfo | None
    message: str
    target: str = ""
    details: dict = field(default_factory=dict)
    changed: bool = True


@dataclass
class _Handler:
    run: Callable[["RepairExecutor", dict, str], _Work]
    plan_key: str
    offline: bool = False  # needs the OS to be shut down → rescue mode only


class RepairExecutor:
    """Runs repair actions under the safety rules, with backup and journal."""

    def __init__(self, config: Config, journal: Journal, backups: BackupManager):
        self.config = config
        self.journal = journal
        self.backups = backups
        self.classifier = SafetyClassifier(config)
        self.demo: DemoSession | None = None

    @property
    def lang(self) -> str:
        return self.config.language

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def plan(self, action: str) -> RepairOutcome:
        """Describe what *action* would do and whether it is allowed — changes nothing."""
        return self._precheck(action, confirmed=True, dry_run=True)

    def execute(
        self, action: str, params: dict | None = None, confirmed: bool = False, session_id: str = "",
    ) -> RepairOutcome:
        """Run *action*. ``params`` must come from server-side state, never straight from a client."""
        outcome = self._precheck(action, confirmed=confirmed, dry_run=False)
        if outcome.status != DONE:
            return outcome

        handler = _HANDLERS[action]
        simulated = self.demo is not None and handler.offline
        run = _simulate if simulated else handler.run
        try:
            work = run(self, {**(params or {}), "action": action}, session_id)
        except _BackupError as exc:
            log.error("Backup for %s failed: %s", action, exc)
            return self._fail(outcome, t("repair.backup_failed", self.lang, error=str(exc)), session_id)
        except Exception as exc:
            log.exception("Repair action %s failed", action)
            return self._fail(outcome, t("repair.failed", self.lang, error=str(exc)), session_id)

        outcome.message = work.message
        outcome.details = work.details
        outcome.simulated = self.demo is not None
        if not work.changed:
            return outcome  # nothing was modified, so there is nothing to journal or undo

        backup = work.backup
        outcome.journal_id = self.journal.record(
            action=action,
            target=work.target,
            details=json.dumps(work.details | {"demo": self.demo.id if self.demo else ""}, ensure_ascii=False),
            risk_level=outcome.risk_level,
            backup_path=backup.backup_path if backup else "",
            rollback_cmd=backup.rollback_cmd if backup else "",
            session_id=session_id,
        )
        outcome.can_rollback = backup is not None
        return outcome

    def rollback(self, journal_id: int) -> bool:
        return self.backups.rollback_entry(journal_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _precheck(self, action: str, confirmed: bool, dry_run: bool) -> RepairOutcome:
        verdict: SafetyVerdict = self.classifier.check(action)
        outcome = RepairOutcome(
            status=DONE,
            action=action,
            risk_level=verdict.risk_level,
            risk_label=verdict.label,
            requires_confirmation=verdict.requires_confirmation,
            requires_backup=verdict.requires_backup,
        )
        handler = _HANDLERS.get(action)
        if handler is not None:
            outcome.plan = t(handler.plan_key, self.lang)
        if not verdict.allowed:
            outcome.status = BLOCKED
            outcome.message = t("repair.blocked", self.lang, reason=verdict.reason)
        elif handler is None:
            outcome.status = UNAVAILABLE
            outcome.message = t("repair.unknown_action", self.lang, action=action)
        elif handler.offline and self.demo is None:
            outcome.status = UNAVAILABLE
            key = "repair.rescue_pending" if self.config.mode == "rescue" else "repair.rescue_only"
            outcome.message = t(key, self.lang)
        elif verdict.requires_confirmation and not confirmed:
            outcome.status = NEEDS_CONFIRMATION
            outcome.message = t("repair.needs_confirmation", self.lang)
        elif dry_run and self.demo is not None:
            outcome.message = t("repair.simulated", self.lang)
        return outcome

    def _fail(self, outcome: RepairOutcome, message: str, session_id: str) -> RepairOutcome:
        outcome.status = FAILED
        outcome.message = message
        outcome.journal_id = self.journal.record(
            action=outcome.action, details=message, risk_level=outcome.risk_level,
            session_id=session_id, status="failed",
        )
        return outcome


class _BackupError(Exception):
    pass


# ----------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------
def _clean_temp_files(ex: RepairExecutor, params: dict, session_id: str) -> _Work:
    """Move stale temporary files into the backup store (undoable until the backup is purged)."""
    if ex.demo is not None:
        dirs, min_age_h = ex.demo.cleanup_dirs(), 0.0
    else:
        dirs = _desktop_temp_dirs()
        min_age_h = float(ex.config.settings.get("safety", {}).get("cleanup_min_age_hours", 24))

    files = _stale_files(dirs, min_age_h, exclude=[str(ex.config.data_dir), str(ex.backups.backup_dir)])
    if not files:
        return _Work(None, t("cleanup.nothing", ex.lang), changed=False)
    try:
        backup = ex.backups.move_to_trash(files, label="cleanup", session_id=session_id, record=False)
    except OSError as exc:
        raise _BackupError(str(exc)) from exc
    if backup.items == 0:
        return _Work(None, t("cleanup.nothing", ex.lang), changed=False, details={"skipped": backup.skipped[:20]})

    size_mb = backup.size_bytes / (1024 * 1024)
    return _Work(
        backup,
        t("cleanup.done", ex.lang, count=backup.items, size_mb=size_mb),
        target=", ".join(dirs),
        details={"files": backup.items, "size_mb": round(size_mb, 2), "skipped": len(backup.skipped)},
    )


def _remove_malware(ex: RepairExecutor, params: dict, session_id: str) -> _Work:
    """Quarantine infected files: they leave their location but can be restored from the journal."""
    files = [f for f in params.get("files", []) if _is_regular_file(f)]
    if not files:
        return _Work(None, t("malware.nothing", ex.lang), changed=False)
    try:
        backup = ex.backups.move_to_trash(files, label="quarantine", session_id=session_id, record=False)
    except OSError as exc:
        raise _BackupError(str(exc)) from exc
    if backup.items == 0:
        raise OSError("; ".join(backup.skipped[:5]))
    return _Work(
        backup,
        t("malware.done", ex.lang, count=backup.items),
        target=", ".join(files),
        details={"files": backup.items, "skipped": len(backup.skipped)},
    )


def _offline_pending(ex: RepairExecutor, params: dict, session_id: str) -> _Work:
    # Offline repairs are gated in _precheck until the rescue build wires them in.
    raise RuntimeError(t("repair.rescue_pending", ex.lang))


def _simulate(ex: RepairExecutor, params: dict, session_id: str) -> _Work:
    """Demo stand-in for offline repairs: back up and "repair" a marker file in the sandbox."""
    action = params["action"]
    marker = ex.demo.marker_file(action)
    try:
        backup = ex.backups.backup_file(str(marker), session_id=session_id, record=False)
    except OSError as exc:
        raise _BackupError(str(exc)) from exc
    marker.write_text(json.dumps({"action": action, "repaired": True, "at": time.time()}), encoding="utf-8")
    return _Work(backup, t("sim.done", ex.lang), target=str(marker), details={"simulated": True})


_HANDLERS: dict[str, _Handler] = {
    "clean_temp_files": _Handler(_clean_temp_files, "cleanup.plan"),
    "remove_malware": _Handler(_remove_malware, "malware.plan"),
    "fix_filesystem": _Handler(_offline_pending, "sim.fix_filesystem", offline=True),
    "fix_bootloader": _Handler(_offline_pending, "sim.fix_bootloader", offline=True),
    "fix_registry_errors": _Handler(_offline_pending, "sim.fix_registry_errors", offline=True),
}


# ----------------------------------------------------------------------
# File selection helpers
# ----------------------------------------------------------------------
def _desktop_temp_dirs() -> list[str]:
    """Temp locations that are safe to prune on a running system (current user only)."""
    dirs = [tempfile.gettempdir()]
    if platform.os_family() == "linux":
        cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        dirs.append(str(Path(cache) / "thumbnails"))
    return [d for d in dirs if os.path.isdir(d)]


def _stale_files(
    dirs: list[str], min_age_hours: float, exclude: list[str] | None = None, limit: int = 50_000,
) -> list[str]:
    """Regular files under *dirs*, owned by us and not modified for *min_age_hours*.

    Directories in *exclude* (our own data and backups) are never descended into.
    """
    cutoff = time.time() - min_age_hours * 3600
    uid = os.getuid() if hasattr(os, "getuid") else None
    skip = {os.path.realpath(e) for e in exclude or []}
    result: list[str] = []
    for root in dirs:
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
            dirnames[:] = [d for d in dirnames if os.path.realpath(os.path.join(dirpath, d)) not in skip]
            if os.path.realpath(dirpath) in skip:
                continue
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode) or st.st_mtime > cutoff:
                    continue
                if uid is not None and st.st_uid != uid:
                    continue
                if not os.access(dirpath, os.W_OK):
                    continue
                result.append(path)
                if len(result) >= limit:
                    return result
    return result


def _is_regular_file(path: str) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False
