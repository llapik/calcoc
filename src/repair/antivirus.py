"""Antivirus operations — quarantine, remove, and manage infected files."""

import os
import shutil
from dataclasses import dataclass, field

from src.core.logger import get_logger
from src.analysis.malware import MalwareHit

log = get_logger("repair.antivirus")

_QUARANTINE_DIR = "/mnt/usb_data/quarantine"


@dataclass
class AVActionResult:
    success: bool = True
    action: str = ""
    files_processed: int = 0
    details: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def quarantine_files(hits: list[MalwareHit], quarantine_dir: str = _QUARANTINE_DIR) -> AVActionResult:
    """Move infected files to quarantine directory."""
    result = AVActionResult(action="quarantine")
    os.makedirs(quarantine_dir, exist_ok=True)

    for hit in hits:
        if not os.path.exists(hit.file_path):
            result.details.append(f"Файл не найден: {hit.file_path}")
            continue

        try:
            # Preserve directory structure in quarantine
            rel_path = hit.file_path.lstrip("/")
            dest = os.path.join(quarantine_dir, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            shutil.move(hit.file_path, dest)
            hit.action_taken = "quarantined"
            result.files_processed += 1
            result.details.append(f"В карантин: {hit.file_path} ({hit.signature})")
            log.info("Quarantined: %s (%s)", hit.file_path, hit.signature)
        except Exception as exc:
            result.errors.append(f"Ошибка карантина {hit.file_path}: {exc}")
            log.warning("Failed to quarantine %s: %s", hit.file_path, exc)

    result.success = len(result.errors) == 0
    return result


def remove_files(hits: list[MalwareHit]) -> AVActionResult:
    """Permanently delete infected files."""
    result = AVActionResult(action="remove")

    for hit in hits:
        if not os.path.exists(hit.file_path):
            result.details.append(f"Файл не найден: {hit.file_path}")
            continue

        try:
            os.unlink(hit.file_path)
            hit.action_taken = "removed"
            result.files_processed += 1
            result.details.append(f"Удалён: {hit.file_path} ({hit.signature})")
            log.info("Removed: %s (%s)", hit.file_path, hit.signature)
        except Exception as exc:
            result.errors.append(f"Ошибка удаления {hit.file_path}: {exc}")

    result.success = len(result.errors) == 0
    return result


def restore_from_quarantine(file_path: str, quarantine_dir: str = _QUARANTINE_DIR) -> AVActionResult:
    """Restore a file from quarantine to its original location."""
    result = AVActionResult(action="restore")
    rel_path = file_path.lstrip("/")
    quarantined = os.path.join(quarantine_dir, rel_path)

    if not os.path.exists(quarantined):
        result.success = False
        result.errors.append(f"Файл не найден в карантине: {quarantined}")
        return result

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        shutil.move(quarantined, file_path)
        result.files_processed = 1
        result.details.append(f"Восстановлен: {file_path}")
        log.info("Restored from quarantine: %s", file_path)
        result.success = True
    except Exception as exc:
        result.success = False
        result.errors.append(f"Ошибка восстановления: {exc}")

    return result
