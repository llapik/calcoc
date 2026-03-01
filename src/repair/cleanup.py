"""System cleanup — remove temp files, caches, and junk from mounted OS partitions."""

import os
import shutil
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("repair.cleanup")

# Windows temp/junk locations (relative to mount point)
_WINDOWS_CLEANUP_PATHS = [
    "Windows/Temp",
    "Windows/Prefetch",
    "Windows/SoftwareDistribution/Download",
    "$Recycle.Bin",
]

_WINDOWS_USER_CLEANUP = [
    "AppData/Local/Temp",
    "AppData/Local/Microsoft/Windows/INetCache",
    "AppData/Local/Microsoft/Windows/Explorer/thumbcache_*.db",
]

# Linux temp locations
_LINUX_CLEANUP_PATHS = [
    "tmp",
    "var/tmp",
    "var/cache/apt/archives",
    "var/cache/pacman/pkg",
]


@dataclass
class CleanupResult:
    success: bool = True
    files_removed: int = 0
    space_freed_mb: float = 0.0
    errors: list[str] = field(default_factory=list)
    paths_cleaned: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"Удалено файлов: {self.files_removed}, "
            f"освобождено: {self.space_freed_mb:.1f} МБ"
        )


def clean_windows(mount_point: str, include_user_dirs: bool = True) -> CleanupResult:
    """Clean temp files from a mounted Windows partition."""
    result = CleanupResult()

    for rel_path in _WINDOWS_CLEANUP_PATHS:
        full_path = os.path.join(mount_point, rel_path)
        _clean_directory(full_path, result)

    if include_user_dirs:
        users_dir = os.path.join(mount_point, "Users")
        if os.path.isdir(users_dir):
            for user in os.listdir(users_dir):
                if user in ("Public", "Default", "Default User", "All Users"):
                    continue
                for rel_path in _WINDOWS_USER_CLEANUP:
                    full_path = os.path.join(users_dir, user, rel_path)
                    _clean_directory(full_path, result)

    return result


def clean_linux(mount_point: str) -> CleanupResult:
    """Clean temp files from a mounted Linux partition."""
    result = CleanupResult()

    for rel_path in _LINUX_CLEANUP_PATHS:
        full_path = os.path.join(mount_point, rel_path)
        _clean_directory(full_path, result)

    return result


def _clean_directory(path: str, result: CleanupResult) -> None:
    """Remove all files in a directory, tracking freed space."""
    if not os.path.isdir(path):
        return

    log.info("Cleaning: %s", path)
    result.paths_cleaned.append(path)

    for entry in os.scandir(path):
        try:
            if entry.is_file(follow_symlinks=False):
                size = entry.stat().st_size
                os.unlink(entry.path)
                result.files_removed += 1
                result.space_freed_mb += size / (1024 * 1024)
            elif entry.is_dir(follow_symlinks=False):
                size = _dir_size(entry.path)
                shutil.rmtree(entry.path, ignore_errors=True)
                result.files_removed += 1
                result.space_freed_mb += size / (1024 * 1024)
        except PermissionError:
            result.errors.append(f"Нет доступа: {entry.path}")
        except Exception as exc:
            result.errors.append(f"{entry.path}: {exc}")


def _dir_size(path: str) -> int:
    """Calculate total size of a directory tree."""
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except OSError:
        pass
    return total
