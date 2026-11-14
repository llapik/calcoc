"""Backup manager — create and restore backups of files, directories and boot records.

Every backup carries a *rollback recipe*: a small JSON document (``{"op": ..., ...}``) stored in the
journal and executed by :meth:`BackupManager.rollback_entry`. Recipes are interpreted in Python —
never passed to a shell — so they work on Windows and cannot be abused through odd file names.
"""

import json
import os
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.core.logger import get_logger
from src.rollback.journal import Journal, JournalEntry

log = get_logger("rollback.backup")

_MBR_SIZE = 512
_MBR_BOOT_CODE = 446  # bootstrap area; the partition table that follows is never restored
_FREE_SPACE_RESERVE = 64 * 1024 * 1024


@dataclass
class BackupInfo:
    backup_id: str = ""
    source_path: str = ""
    backup_path: str = ""
    backup_type: str = ""  # file | directory | mbr | partition_table | trash
    timestamp: float = 0.0
    size_bytes: int = 0
    rollback: dict = field(default_factory=dict)
    items: int = 0
    skipped: list[str] = field(default_factory=list)

    @property
    def rollback_cmd(self) -> str:
        return json.dumps(self.rollback, ensure_ascii=False)


class BackupManager:
    """Manages backups stored in the application data directory (USB data partition in rescue mode)."""

    def __init__(self, backup_dir: str | Path, journal: Journal):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.journal = journal

    # ------------------------------------------------------------------
    # Public backup methods
    # ------------------------------------------------------------------
    def backup_file(self, source: str, session_id: str = "", record: bool = True) -> BackupInfo:
        """Backup a single file."""
        backup = self._make_backup_info(source, "file")
        shutil.copy2(source, backup.backup_path)
        backup.size_bytes = Path(backup.backup_path).stat().st_size
        backup.rollback = {"op": "copy_file", "src": backup.backup_path, "dst": str(source)}
        return self._finish(backup, "backup_file", "yellow", session_id, record)

    def backup_directory(self, source: str, session_id: str = "", record: bool = True) -> BackupInfo:
        """Backup an entire directory as a .tar.gz archive."""
        backup = self._make_backup_info(source, "directory")
        backup.backup_path += ".tar.gz"
        src = Path(source).resolve()
        with tarfile.open(backup.backup_path, "w:gz") as tar:
            tar.add(src, arcname=src.name)
        backup.size_bytes = Path(backup.backup_path).stat().st_size
        backup.rollback = {"op": "extract_tar", "src": backup.backup_path, "dst": str(src.parent)}
        return self._finish(backup, "backup_directory", "yellow", session_id, record)

    def backup_mbr(self, device: str, session_id: str = "", record: bool = True) -> BackupInfo:
        """Backup the MBR (first 512 bytes) of a block device."""
        backup = self._make_backup_info(device, "mbr")
        backup.backup_path += ".mbr"
        with open(device, "rb") as src:
            data = src.read(_MBR_SIZE)
        if len(data) != _MBR_SIZE:
            raise OSError(f"Short read from {device}: {len(data)} bytes")
        Path(backup.backup_path).write_bytes(data)
        backup.size_bytes = _MBR_SIZE
        backup.rollback = {"op": "write_mbr", "src": backup.backup_path, "dst": str(device)}
        return self._finish(backup, "backup_mbr", "red", session_id, record)

    def backup_partition_table(self, device: str, session_id: str = "", record: bool = True) -> BackupInfo:
        """Backup the partition table using sfdisk (Linux only)."""
        backup = self._make_backup_info(device, "partition_table")
        backup.backup_path += ".sfdisk"
        with open(backup.backup_path, "w") as fh:
            subprocess.check_call(
                ["sfdisk", "--dump", device],
                stdout=fh, timeout=30, stderr=subprocess.DEVNULL,
            )
        backup.size_bytes = Path(backup.backup_path).stat().st_size
        backup.rollback = {"op": "sfdisk_restore", "src": backup.backup_path, "dst": str(device)}
        return self._finish(backup, "backup_partition_table", "red", session_id, record)

    def move_to_trash(
        self, files: list[str], label: str = "trash", session_id: str = "", record: bool = True,
    ) -> BackupInfo:
        """Move *files* into the backup store, keeping a manifest so each can be put back.

        Used by cleanup and quarantine: the "deletion" itself is the backup. Files that cannot be
        moved (in use, no permission, backup volume full) are listed in ``skipped``.
        """
        backup = self._make_backup_info(label, "trash")
        root = Path(backup.backup_path)
        store = root / "files"
        store.mkdir(parents=True)
        manifest: list[dict] = []

        for n, original in enumerate(files):
            src = Path(original)
            try:
                size = src.lstat().st_size
                if shutil.disk_usage(root).free < size + _FREE_SPACE_RESERVE:
                    backup.skipped.append(f"{original}: backup volume full")
                    continue
                stored = store / f"{n:06d}"
                shutil.move(str(src), stored)
                manifest.append({"original": str(src), "stored": str(stored), "size": size})
                backup.size_bytes += size
            except OSError as exc:
                backup.skipped.append(f"{original}: {exc.strerror or exc}")

        backup.items = len(manifest)
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        backup.rollback = {"op": "restore_manifest", "manifest": str(manifest_path)}
        return self._finish(backup, f"backup_{label}", "yellow", session_id, record)

    # ------------------------------------------------------------------
    # Restore / Rollback
    # ------------------------------------------------------------------
    def rollback_entry(self, entry_id: int) -> bool:
        """Undo the journal entry *entry_id* using its stored rollback recipe."""
        entry = self.journal.get_entry(entry_id)
        if entry is None or not self.can_rollback(entry):
            log.error("Journal entry #%s cannot be rolled back", entry_id)
            return False

        log.info("Rolling back journal entry #%d: %s", entry.id, entry.action)
        try:
            self._run_recipe(json.loads(entry.rollback_cmd))
        except Exception as exc:
            log.error("Rollback failed for entry #%d: %s", entry.id, exc)
            return False
        self.journal.update_status(entry.id, "rolled_back")
        log.info("Rollback successful for entry #%d", entry.id)
        return True

    @staticmethod
    def can_rollback(entry: JournalEntry) -> bool:
        return entry.status == "completed" and entry.rollback_cmd.startswith("{")

    def restore(self, backup_path: str) -> bool:
        """Roll back the most recent completed journal entry that owns *backup_path*."""
        entry = self.journal.get_entry_by_backup_path(backup_path)
        if entry is None:
            log.error("No journal entry found for backup: %s", backup_path)
            return False
        return self.rollback_entry(entry.id)

    def rollback_last(self, session_id: str = "") -> bool:
        """Roll back the most recent completed operation (optionally within a session)."""
        entries = (
            self.journal.get_session_entries(session_id)
            if session_id
            else self.journal.get_rollbackable()
        )
        for entry in entries:
            if self.can_rollback(entry):
                return self.rollback_entry(entry.id)

        log.warning("No rollbackable entries found")
        return False

    def purge(self, older_than_hours: float = 0) -> tuple[int, int]:
        """Delete backup payloads of completed entries. Returns ``(entries, bytes_released)``.

        Purged operations can no longer be rolled back.
        """
        cutoff = time.time() - older_than_hours * 3600
        count = released = 0
        for entry in self.journal.get_rollbackable():
            if entry.timestamp > cutoff:
                continue
            path = Path(entry.backup_path)
            try:
                path.relative_to(self.backup_dir)
            except ValueError:
                continue  # never delete anything outside the backup store
            released += _tree_size(path)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            self.journal.update_status(entry.id, "purged")
            count += 1
        return count, released

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _run_recipe(self, recipe: dict) -> None:
        op = recipe.get("op")
        if op == "copy_file":
            shutil.copy2(recipe["src"], recipe["dst"])
        elif op == "extract_tar":
            with tarfile.open(recipe["src"], "r:gz") as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(recipe["dst"], filter="data")
                else:  # Python < 3.12 without the backported filter
                    tar.extractall(recipe["dst"])
        elif op == "write_mbr":
            data = Path(recipe["src"]).read_bytes()[:_MBR_BOOT_CODE]
            with open(recipe["dst"], "r+b") as dev:
                dev.write(data)
                dev.flush()
                os.fsync(dev.fileno())
        elif op == "sfdisk_restore":
            with open(recipe["src"], "r") as fh:
                subprocess.check_call(["sfdisk", recipe["dst"]], stdin=fh, timeout=60)
        elif op == "restore_manifest":
            manifest = json.loads(Path(recipe["manifest"]).read_text(encoding="utf-8"))
            for item in manifest:
                stored, original = Path(item["stored"]), Path(item["original"])
                if not stored.exists():
                    continue
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(stored), original)
        elif op == "multi":
            for step in recipe.get("steps", []):
                self._run_recipe(step)
        else:
            raise ValueError(f"Unknown rollback op: {op!r}")

    def _finish(self, backup: BackupInfo, action: str, risk: str, session_id: str, record: bool) -> BackupInfo:
        if record:
            self.journal.record(
                action=action,
                target=backup.source_path,
                risk_level=risk,
                backup_path=backup.backup_path,
                rollback_cmd=backup.rollback_cmd,
                session_id=session_id,
            )
        log.info("Backup (%s): %s -> %s", backup.backup_type, backup.source_path, backup.backup_path)
        return backup

    def _make_backup_info(self, source: str, backup_type: str) -> BackupInfo:
        ts = time.time()
        safe_name = "".join(c if c.isalnum() or c in "-." else "_" for c in str(source)).strip("_")[:100]
        backup_id = f"{time.time_ns() // 1000}_{safe_name}"
        return BackupInfo(
            backup_id=backup_id,
            source_path=str(source),
            backup_path=str(self.backup_dir / backup_id),
            backup_type=backup_type,
            timestamp=ts,
        )


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
