"""Minimal message catalogue for backend-generated user-facing text (Russian primary, English)."""

_MESSAGES: dict[str, dict[str, str]] = {
    "repair.blocked": {
        "ru": "Заблокировано: {reason}",
        "en": "Blocked: {reason}",
    },
    "repair.needs_confirmation": {
        "ru": "Требуется подтверждение",
        "en": "Confirmation required",
    },
    "repair.unknown_action": {
        "ru": "Для действия «{action}» нет обработчика",
        "en": "No handler for action “{action}”",
    },
    "repair.rescue_only": {
        "ru": "Это исправление выполняется только при загрузке с флешки: систему нельзя чинить, пока она запущена",
        "en": "This fix only runs when booted from the USB stick: the system cannot be repaired while it is running",
    },
    "repair.rescue_pending": {
        "ru": "Офлайн-ремонт будет доступен в сборке для загрузочной флешки",
        "en": "Offline repair will be available in the bootable USB build",
    },
    "repair.failed": {
        "ru": "Не удалось выполнить: {error}",
        "en": "Failed: {error}",
    },
    "repair.backup_failed": {
        "ru": "Не удалось создать резервную копию, действие отменено: {error}",
        "en": "Backup failed, action cancelled: {error}",
    },
    "repair.simulated": {
        "ru": "Демо-режим: действие смоделировано, реальная система не изменена",
        "en": "Demo mode: the action was simulated, the real system was not changed",
    },
    "cleanup.plan": {
        "ru": "Временные файлы будут перемещены в резервную копию. Место освободится после её удаления",
        "en": "Temporary files will be moved to a backup. Space is released once the backup is purged",
    },
    "cleanup.done": {
        "ru": "Убрано файлов: {count}, {size_mb:.1f} МБ. Можно откатить в журнале",
        "en": "Files removed: {count}, {size_mb:.1f} MB. Can be undone from the journal",
    },
    "cleanup.nothing": {
        "ru": "Подходящих временных файлов не найдено",
        "en": "No matching temporary files found",
    },
    "malware.plan": {
        "ru": "Заражённые файлы будут перемещены в карантин",
        "en": "Infected files will be moved to quarantine",
    },
    "malware.done": {
        "ru": "В карантин перемещено файлов: {count}",
        "en": "Files moved to quarantine: {count}",
    },
    "malware.nothing": {
        "ru": "Файлы не найдены — возможно, уже удалены",
        "en": "Files not found — possibly already removed",
    },
    "sim.fix_filesystem": {
        "ru": "Проверка и исправление файловой системы (e2fsck / ntfsfix) на отмонтированном разделе",
        "en": "Filesystem check and repair (e2fsck / ntfsfix) on the unmounted partition",
    },
    "sim.fix_bootloader": {
        "ru": "Резервная копия MBR, затем переустановка загрузчика",
        "en": "MBR backup, then bootloader reinstall",
    },
    "sim.fix_registry_errors": {
        "ru": "Резервная копия кустов реестра, затем удаление повреждённых записей автозагрузки",
        "en": "Registry hive backup, then removal of broken autorun entries",
    },
    "sim.done": {
        "ru": "Выполнено (демо)",
        "en": "Done (demo)",
    },
    "rollback.done": {"ru": "Операция #{id} отменена", "en": "Operation #{id} rolled back"},
    "rollback.failed": {"ru": "Не удалось отменить операцию #{id}", "en": "Could not roll back operation #{id}"},
    "rollback.not_possible": {
        "ru": "Операцию #{id} нельзя отменить",
        "en": "Operation #{id} cannot be rolled back",
    },
    "purge.done": {
        "ru": "Удалено резервных копий: {count}, освобождено {size_mb:.1f} МБ",
        "en": "Backups purged: {count}, {size_mb:.1f} MB released",
    },
    "scan.required": {"ru": "Сначала выполните диагностику", "en": "Run a diagnostic scan first"},
    "problem.not_found": {"ru": "Проблема не найдена", "en": "Problem not found"},
    "problem.not_fixable": {
        "ru": "Для этой проблемы нет автоматического исправления",
        "en": "There is no automatic fix for this problem",
    },
    "demo.unknown": {"ru": "Неизвестный демо-сценарий", "en": "Unknown demo scenario"},
}


def t(key: str, lang: str = "ru", **fmt) -> str:
    """Translate *key* into *lang* (falls back to Russian, then to the key itself)."""
    entry = _MESSAGES.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry["ru"]
    return text.format(**fmt) if fmt else text


def pick(value, lang: str = "ru") -> str:
    """Pick a language from a ``{"ru": ..., "en": ...}`` dict; plain strings pass through."""
    if isinstance(value, dict):
        return value.get(lang) or value.get("ru") or next(iter(value.values()), "")
    return value or ""
