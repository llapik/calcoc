"""Backup manager — create and restore backups of files, partitions, and boot records."""

import os
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
        # Ensure the parent directory of the backup path exists
        Path(backup.backup_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup.backup_path)
        backup.size_bytes = os.path.getsize(backup.backup_path)

        self.journal.record(
            action="backup_file",
            target=source,
            backup_path=backup.backup_path,
            rollback_cmd=f"cp -p '{backup.backup_path}' '{source}'",
            session_id=session_id,
        )
        log.info("File backed up: %s -> %s", source, backup.backup_path)
        return backup

    def backup_directory(self, source: str, session_id: str = "") -> BackupInfo:
        """Backup an entire directory as a .tar.gz archive."""
        backup = self._make_backup_info(source, "directory")
        backup.backup_path += ".tar.gz"
        Path(backup.backup_path).parent.mkdir(parents=True, exist_ok=True)

        subprocess.check_call(
            ["tar", "czf", backup.backup_path, "-C",
             os.path.dirname(os.path.abspath(source)), os.path.basename(source)],
            timeout=600,
        )
        backup.size_bytes = os.path.getsize(backup.backup_path)

        self.journal.record(
            action="backup_directory",
            target=source,
            backup_path=backup.backup_path,
            rollback_cmd=(
                f"tar xzf '{backup.backup_path}' "
                f"-C '{os.path.dirname(os.path.abspath(source))}'"
            ),
            session_id=session_id,
        )
        log.info("Directory backed up: %s -> %s", source, backup.backup_path)
        return backup

    def backup_mbr(self, device: str, session_id: str = "") -> BackupInfo:
        """Backup MBR (first 512 bytes) of a block device."""
        backup = self._make_backup_info(device, "mbr")
        backup.backup_path += ".mbr"
        Path(backup.backup_path).parent.mkdir(parents=True, exist_ok=True)

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
            rollback_cmd=f"dd if='{backup.backup_path}' of='{device}' bs=446 count=1",
            session_id=session_id,
        )
        log.info("MBR backed up: %s -> %s", device, backup.backup_path)
        return backup

    def backup_partition_table(self, device: str, session_id: str = "") -> BackupInfo:
        """Backup partition table using sfdisk."""
        backup = self._make_backup_info(device, "partition_table")
        backup.backup_path += ".sfdisk"
        Path(backup.backup_path).parent.mkdir(parents=True, exist_ok=True)

        with open(backup.backup_path, "w") as fh:
            subprocess.check_call(
                ["sfdisk", "--dump", device],
                stdout=fh, timeout=30, stderr=subprocess.DEVNULL,
            )
        backup.size_bytes = os.path.getsize(backup.backup_path)

        self.journal.record(
            action="backup_partition_table",
            target=device,
            risk_level="red",
            backup_path=backup.backup_path,
            rollback_cmd=f"sfdisk '{device}' < '{backup.backup_path}'",
            session_id=session_id,
        )
        log.info("Partition table backed up: %s -> %s", device, backup.backup_path)
        return backup

    # ------------------------------------------------------------------
    # Restore / Rollback
    # ------------------------------------------------------------------
    def restore(self, backup_path: str) -> bool:
        """Execute the rollback command stored in the journal for this backup."""
        for entry in self.journal.get_rollbackable():
            if entry.backup_path == backup_path:
                log.info("Rolling back journal entry #%d: %s", entry.id, entry.action)
                try:
                    subprocess.check_call(
                        entry.rollback_cmd, shell=True, timeout=600,
                    )
                    self.journal.update_status(entry.id, "rolled_back")
                    log.info("Rollback successful for entry #%d", entry.id)
                    return True
                except Exception as exc:
                    log.error("Rollback failed for entry #%d: %s", entry.id, exc)
                    self.journal.update_status(entry.id, "failed")
                    return False

        log.error("No journal entry found for backup: %s", backup_path)
        return False

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
        backup_path = str(self.backup_dir / backup_id)
        return BackupInfo(
            backup_id=backup_id,
            source_path=source,
            backup_path=backup_path,
            backup_type=backup_type,
            timestamp=ts,
        )
