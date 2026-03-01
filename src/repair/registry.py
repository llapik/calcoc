"""Windows registry repair — offline hive manipulation."""

import os
import shutil
from dataclasses import dataclass, field

from src.core.logger import get_logger

log = get_logger("repair.registry")


@dataclass
class RegistryRepairResult:
    success: bool = False
    action: str = ""
    details: str = ""
    fixes_applied: list[str] = field(default_factory=list)
    backup_path: str = ""


# Common registry issues and their fixes
_KNOWN_FIXES = [
    {
        "hive": "SYSTEM",
        "description": "Проверка целостности SYSTEM hive",
        "check_keys": ["ControlSet001\\Control", "Select"],
    },
    {
        "hive": "SOFTWARE",
        "description": "Проверка ключей автозагрузки",
        "check_keys": [
            "Microsoft\\Windows\\CurrentVersion\\Run",
            "Microsoft\\Windows\\CurrentVersion\\RunOnce",
        ],
    },
]


def find_registry_hives(windows_mount: str) -> dict[str, str]:
    """Find Windows registry hive files on a mounted partition."""
    config_dir = os.path.join(windows_mount, "Windows", "System32", "config")
    hives = {}

    for hive_name in ["SYSTEM", "SOFTWARE", "SAM", "SECURITY", "DEFAULT"]:
        hive_path = os.path.join(config_dir, hive_name)
        if os.path.isfile(hive_path):
            hives[hive_name] = hive_path

    # User hives
    users_dir = os.path.join(windows_mount, "Users")
    if os.path.isdir(users_dir):
        for user_dir in os.listdir(users_dir):
            ntuser = os.path.join(users_dir, user_dir, "NTUSER.DAT")
            if os.path.isfile(ntuser):
                hives[f"NTUSER_{user_dir}"] = ntuser

    return hives


def backup_hive(hive_path: str, backup_dir: str) -> str:
    """Create a backup of a registry hive file."""
    os.makedirs(backup_dir, exist_ok=True)
    filename = os.path.basename(hive_path)
    backup_path = os.path.join(backup_dir, f"{filename}.bak")
    shutil.copy2(hive_path, backup_path)
    log.info("Registry hive backed up: %s -> %s", hive_path, backup_path)
    return backup_path


def check_hive_integrity(hive_path: str) -> RegistryRepairResult:
    """Check if a registry hive can be parsed without errors."""
    result = RegistryRepairResult(action="check_registry")

    try:
        from Registry import Registry as RegistryParser

        reg = RegistryParser.Registry(hive_path)
        root = reg.root()
        # Walk the tree to find corruption
        errors = []
        _walk_key(root, errors, max_depth=5)

        if errors:
            result.details = f"Обнаружены ошибки ({len(errors)}): {'; '.join(errors[:5])}"
            result.success = True
        else:
            result.details = f"Реестр {os.path.basename(hive_path)} — ошибок не обнаружено"
            result.success = True
    except ImportError:
        result.details = "Библиотека python-registry не установлена"
        result.success = False
    except Exception as exc:
        result.details = f"Ошибка чтения реестра: {exc}"
        result.success = False

    return result


def clean_autorun_entries(
    hive_path: str,
    backup_dir: str,
    suspicious_patterns: list[str] | None = None,
) -> RegistryRepairResult:
    """Remove suspicious autorun entries from SOFTWARE hive.

    Note: This uses offline hive editing and is a simplified approach.
    Full registry editing requires hivex or python-registry with write support.
    """
    result = RegistryRepairResult(action="clean_autorun")

    if suspicious_patterns is None:
        suspicious_patterns = [
            "temp\\\\", "appdata\\\\local\\\\temp", "%temp%",
            ".vbs", ".bat", ".cmd",
        ]

    try:
        from Registry import Registry as RegistryParser

        # Backup first
        result.backup_path = backup_hive(hive_path, backup_dir)

        reg = RegistryParser.Registry(hive_path)
        autorun_paths = [
            "Microsoft\\Windows\\CurrentVersion\\Run",
            "Microsoft\\Windows\\CurrentVersion\\RunOnce",
        ]

        for key_path in autorun_paths:
            try:
                key = reg.open(key_path)
                for value in key.values():
                    val_data = str(value.value()).lower()
                    for pattern in suspicious_patterns:
                        if pattern.lower() in val_data:
                            result.fixes_applied.append(
                                f"Подозрительная запись: {value.name()} = {value.value()}"
                            )
                            break
            except Exception:
                continue

        if result.fixes_applied:
            result.details = (
                f"Найдено {len(result.fixes_applied)} подозрительных записей автозагрузки. "
                "Для их удаления требуется hivex (запись в реестр). "
                "Записи сохранены в журнале для ручного удаления."
            )
        else:
            result.details = "Подозрительных записей автозагрузки не найдено"

        result.success = True
    except ImportError:
        result.details = "Библиотека python-registry не установлена"
        result.success = False
    except Exception as exc:
        result.details = f"Ошибка: {exc}"
        result.success = False

    return result


def _walk_key(key, errors: list, max_depth: int, depth: int = 0) -> None:
    """Recursively walk registry keys looking for corruption."""
    if depth >= max_depth:
        return
    try:
        for subkey in key.subkeys():
            try:
                _ = subkey.name()
                _walk_key(subkey, errors, max_depth, depth + 1)
            except Exception as exc:
                errors.append(f"Corrupt key at depth {depth}: {exc}")
    except Exception as exc:
        errors.append(f"Cannot enumerate subkeys at depth {depth}: {exc}")
