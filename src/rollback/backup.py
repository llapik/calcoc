"""Backup manager — create and restore backups of files, partitions, and boot records."""

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from src.core.logger import get_logger
from src.rollback.journal import Journal

log = get_logger("rollback.backup")


@dataclass
class BackupInfo:
    backup_id: str = ""
    source_path: str = ""
    backup_path: str = ""
    backup_type: str = ""  # file | directory | mbr | partition_table | registry
    timestamp: float = 0.0
    size_bytes: int = 0


class BackupManager:
    """Manages backups stored on the USB data partition."""

    def __init__(self, backup_dir: str | Path, journal: Journal):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.journal = journal

    # ------------------------------------------------------------------
    # Public backup methods
    # ------------------------------------------------------------------
    def backup_file(self, source: str, session_id: str = "") -> BackupInfo:
        """Backup a single file."""
        backup = self._make_backup_info(source, "file")
        shutil.copy2(source, backup.backup_path)
        backup.size_bytes = Path(backup.backup_path).stat().st_size

        self.journal.record(
            action="backup_file",
            target=source,
            backup_path=backup.backup_path,
            rollback_cmd=json.dumps(["cp", "-p", backup.backup_path, source]),
            session_id=session_id,
        )
        log.info("File backed up: %s -> %s", source, backup.backup_path)
        return backup

    def backup_directory(self, source: str, session_id: str = "") -> BackupInfo:
        """Backup an entire directory as a .tar.gz archive."""
        backup = self._make_backup_info(source, "directory")
        backup.backup_path += ".tar.gz"
        src = Path(source).resolve()

        subprocess.check_call(
            ["tar", "czf", backup.backup_path, "-C", str(src.parent), src.name],
            timeout=600,
        )
        backup.size_bytes = Path(backup.backup_path).stat().st_size

        self.journal.record(
            action="backup_directory",
            target=source,
            backup_path=backup.backup_path,
            rollback_cmd=json.dumps(["tar", "xzf", backup.backup_path, "-C", str(src.parent)]),
            session_id=session_id,
        )
        log.info("Directory backed up: %s -> %s", source, backup.backup_path)
        return backup

    def backup_mbr(self, device: str, session_id: str = "") -> BackupInfo:
        """Backup MBR (first 512 bytes) of a block device."""
        backup = self._make_backup_info(device, "mbr")
        backup.backup_path += ".mbr"

        subprocess.check_call(
            ["dd", f"if={device}", f"of={backup.backup_path}", "bs=512", "count=1"],
            timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        backup.size_bytes = 512

        self.journal.record(
            action="backup_mbr",
            target=device,
            risk_level="red",
            backup_path=backup.backup_path,
            # Restore only the bootstrap code (446 bytes), preserving the partition table
            rollback_cmd=json.dumps(
                ["dd", f"if={backup.backup_path}", f"of={device}", "bs=446", "count=1"]
            ),
            session_id=session_id,
        )
        log.info("MBR backed up: %s -> %s", device, backup.backup_path)
        return backup

    def backup_partition_table(self, device: str, session_id: str = "") -> BackupInfo:
        """Backup partition table using sfdisk."""
        backup = self._make_backup_info(device, "partition_table")
        backup.backup_path += ".sfdisk"

        with open(backup.backup_path, "w") as fh:
            subprocess.check_call(
                ["sfdisk", "--dump", device],
                stdout=fh, timeout=30, stderr=subprocess.DEVNULL,
            )
        backup.size_bytes = Path(backup.backup_path).stat().st_size

        self.journal.record(
            action="backup_partition_table",
            target=device,
            risk_level="red",
            backup_path=backup.backup_path,
            # stdin is fed from backup_path by _exec_rollback — no shell redirection needed
            rollback_cmd=json.dumps(["sfdisk", device]),
            session_id=session_id,
        )
        log.info("Partition table backed up: %s -> %s", device, backup.backup_path)
        return backup

    # ------------------------------------------------------------------
    # Restore / Rollback
    # ------------------------------------------------------------------
    def restore(self, backup_path: str) -> bool:
        """Execute the rollback command stored in the journal for this backup."""
        entry = self.journal.get_entry_by_backup_path(backup_path)
        if entry is None:
            log.error("No journal entry found for backup: %s", backup_path)
            return False

        log.info("Rolling back journal entry #%d: %s", entry.id, entry.action)
        try:
            self._exec_rollback(entry)
            self.journal.update_status(entry.id, "rolled_back")
            log.info("Rollback successful for entry #%d", entry.id)
            return True
        except Exception as exc:
            log.error("Rollback failed for entry #%d: %s", entry.id, exc)
            self.journal.update_status(entry.id, "failed")
            return False

    def _exec_rollback(self, entry) -> None:
        """Execute a rollback command without shell=True (no injection risk).

        Commands are stored as JSON arrays.  The only special case is
        backup_partition_table where sfdisk reads the partition layout from
        stdin rather than a shell-redirect.
        """
        try:
            cmd = json.loads(entry.rollback_cmd)
            if not isinstance(cmd, list) or not cmd:
                raise ValueError("rollback_cmd is not a non-empty list")
        except (json.JSONDecodeError, ValueError):
            # Backward-compat: legacy entries may hold raw shell strings.
            log.warning("Legacy shell rollback_cmd for entry #%d; falling back to shell=True", entry.id)
            subprocess.check_call(entry.rollback_cmd, shell=True, timeout=600)
            return

        if entry.action == "backup_partition_table" and entry.backup_path:
            # Feed saved partition layout into sfdisk via stdin instead of shell '<'
            with open(entry.backup_path) as fh:
                subprocess.check_call(cmd, stdin=fh, timeout=60)
        else:
            subprocess.check_call(cmd, timeout=600)

    def rollback_last(self, session_id: str = "") -> bool:
        """Roll back the most recent completed operation (optionally within a session)."""
        entries = (
            self.journal.get_session_entries(session_id)
            if session_id
            else self.journal.get_rollbackable()
        )
        for entry in entries:
            if entry.status == "completed" and entry.backup_path:
                return self.restore(entry.backup_path)

        log.warning("No rollbackable entries found")
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _make_backup_info(self, source: str, backup_type: str) -> BackupInfo:
        ts = time.time()
        safe_name = source.replace("/", "_").strip("_")[:120]
        backup_id = f"{int(ts)}_{safe_name}"
        backup_path = self.backup_dir / backup_id
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        return BackupInfo(
            backup_id=backup_id,
            source_path=source,
            backup_path=str(backup_path),
            backup_type=backup_type,
            timestamp=ts,
        )
