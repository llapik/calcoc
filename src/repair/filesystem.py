"""Filesystem repair — fsck, chkdsk, and filesystem checks."""

import subprocess
from dataclasses import dataclass

from src.core.logger import get_logger

log = get_logger("repair.fs")


@dataclass
class RepairResult:
    success: bool = False
    action: str = ""
    details: str = ""
    changes_made: list[str] | None = None


def check_filesystem(device: str, fs_type: str) -> RepairResult:
    """Check a filesystem for errors (read-only check)."""
    if fs_type in ("ext4", "ext3", "ext2"):
        return _check_ext(device)
    elif fs_type == "ntfs":
        return _check_ntfs(device)
    else:
        return RepairResult(
            success=False,
            action="check_filesystem",
            details=f"Файловая система {fs_type} не поддерживается для проверки",
        )


def fix_filesystem(device: str, fs_type: str) -> RepairResult:
    """Repair a filesystem (requires unmounted partition)."""
    if fs_type in ("ext4", "ext3", "ext2"):
        return _fix_ext(device)
    elif fs_type == "ntfs":
        return _fix_ntfs(device)
    else:
        return RepairResult(
            success=False,
            action="fix_filesystem",
            details=f"Автоматическое исправление {fs_type} не поддерживается",
        )


def _check_ext(device: str) -> RepairResult:
    """Check ext2/3/4 filesystem using e2fsck in read-only mode."""
    try:
        proc = subprocess.run(
            ["e2fsck", "-n", device],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode == 0:
            return RepairResult(
                success=True,
                action="check_filesystem",
                details=f"Файловая система {device} в порядке",
            )
        else:
            return RepairResult(
                success=True,
                action="check_filesystem",
                details=f"Обнаружены ошибки на {device}:\n{proc.stdout}",
            )
    except Exception as exc:
        return RepairResult(success=False, action="check_filesystem", details=str(exc))


def _fix_ext(device: str) -> RepairResult:
    """Repair ext2/3/4 filesystem using e2fsck."""
    try:
        proc = subprocess.run(
            ["e2fsck", "-y", "-f", device],
            capture_output=True, text=True, timeout=1800,
        )
        changes = []
        for line in proc.stdout.splitlines():
            if line.strip():
                changes.append(line.strip())

        return RepairResult(
            success=proc.returncode in (0, 1),
            action="fix_filesystem",
            details=f"Исправление файловой системы {device} завершено",
            changes_made=changes,
        )
    except Exception as exc:
        return RepairResult(success=False, action="fix_filesystem", details=str(exc))


def _check_ntfs(device: str) -> RepairResult:
    """Check NTFS filesystem using ntfsfix in read-only mode."""
    try:
        proc = subprocess.run(
            ["ntfsfix", "-n", device],
            capture_output=True, text=True, timeout=300,
        )
        return RepairResult(
            success=True,
            action="check_filesystem",
            details=proc.stdout.strip(),
        )
    except Exception as exc:
        return RepairResult(success=False, action="check_filesystem", details=str(exc))


def _fix_ntfs(device: str) -> RepairResult:
    """Repair NTFS filesystem using ntfsfix."""
    try:
        proc = subprocess.run(
            ["ntfsfix", device],
            capture_output=True, text=True, timeout=600,
        )
        return RepairResult(
            success=proc.returncode == 0,
            action="fix_filesystem",
            details=proc.stdout.strip(),
            changes_made=proc.stdout.strip().splitlines(),
        )
    except Exception as exc:
        return RepairResult(success=False, action="fix_filesystem", details=str(exc))
