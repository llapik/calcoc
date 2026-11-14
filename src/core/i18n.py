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
    # --- performance findings -------------------------------------------------
    "perf.cpu_load": {"ru": "Загрузка процессора: {v:.0f}%", "en": "CPU load: {v:.0f}%"},
    "perf.cpu_load.rec": {
        "ru": "Проверьте запущенные процессы — возможно, есть зависшие или лишние приложения",
        "en": "Check running processes — something may be stuck or unnecessary",
    },
    "perf.cpu_temp_critical": {
        "ru": "Температура процессора: {v:.0f}°C (критически высокая)",
        "en": "CPU temperature: {v:.0f}°C (critically high)",
    },
    "perf.cpu_temp_critical.rec": {
        "ru": "Проверьте охлаждение: термопасту, вентиляторы, радиатор",
        "en": "Check the cooling: thermal paste, fans, heatsink",
    },
    "perf.cpu_temp_high": {
        "ru": "Температура процессора: {v:.0f}°C (повышенная)",
        "en": "CPU temperature: {v:.0f}°C (elevated)",
    },
    "perf.cpu_temp_high.rec": {
        "ru": "Рекомендуется чистка системы охлаждения",
        "en": "Cleaning the cooling system is recommended",
    },
    "perf.single_core": {
        "ru": "Одноядерный процессор — ограниченная многозадачность",
        "en": "Single-core CPU — limited multitasking",
    },
    "perf.single_core.rec": {
        "ru": "Рассмотрите апгрейд на многоядерный процессор",
        "en": "Consider upgrading to a multi-core CPU",
    },
    "perf.ram_critical": {
        "ru": "Память занята на {v:.0f}% ({used} из {total} МБ)",
        "en": "Memory is {v:.0f}% used ({used} of {total} MB)",
    },
    "perf.ram_critical.rec": {
        "ru": "Закройте неиспользуемые приложения или увеличьте объём памяти",
        "en": "Close unused applications or add more memory",
    },
    "perf.ram_high": {"ru": "Память занята на {v:.0f}%", "en": "Memory is {v:.0f}% used"},
    "perf.ram_high.rec": {"ru": "Рассмотрите увеличение объёма памяти", "en": "Consider adding memory"},
    "perf.ram_small": {"ru": "Мало памяти: {total} МБ", "en": "Low memory: {total} MB"},
    "perf.ram_small.rec": {
        "ru": "Для комфортной работы нужно минимум 8 ГБ",
        "en": "At least 8 GB is needed for comfortable use",
    },
    "perf.swap": {
        "ru": "Активно используется файл подкачки ({v:.0f}%)",
        "en": "Swap is heavily used ({v:.0f}%)",
    },
    "perf.swap.rec": {
        "ru": "Системе не хватает памяти — добавьте ОЗУ для ускорения",
        "en": "The system is short of memory — add RAM to speed it up",
    },
    "perf.smart_failing": {
        "ru": "Диск {model} ({device}) — S.M.A.R.T. сообщает о сбое",
        "en": "Disk {model} ({device}) — S.M.A.R.T. reports failure",
    },
    "perf.smart_failing.rec": {
        "ru": "Срочно сделайте резервную копию данных: диск может выйти из строя",
        "en": "Back up your data now: the disk may fail",
    },
    "perf.disk_temp": {"ru": "Температура диска {model}: {v}°C", "en": "Disk {model} temperature: {v}°C"},
    "perf.disk_temp.rec": {"ru": "Проверьте вентиляцию корпуса", "en": "Check case ventilation"},
    "perf.hdd_slow": {"ru": "Жёсткий диск {model} — медленнее SSD", "en": "Hard drive {model} — slower than an SSD"},
    "perf.hdd_slow.rec": {
        "ru": "Замена на SSD заметно ускорит загрузку и работу системы",
        "en": "Replacing it with an SSD noticeably speeds up boot and everyday work",
    },
    "perf.partition_full": {
        "ru": "Раздел {device} заполнен на {v:.0f}%",
        "en": "Partition {device} is {v:.0f}% full",
    },
    "perf.partition_full.rec": {
        "ru": "Освободите место: очистите временные файлы или перенесите данные",
        "en": "Free up space: clean temporary files or move data elsewhere",
    },
    "perf.gpu_temp": {"ru": "Температура видеокарты {model}: {v}°C", "en": "GPU {model} temperature: {v}°C"},
    "perf.gpu_temp.rec": {"ru": "Проверьте охлаждение видеокарты", "en": "Check the graphics card cooling"},
    "perf.summary.ok": {
        "ru": "Оценка производительности: {score}/100 — проблем не обнаружено",
        "en": "Performance score: {score}/100 — no problems found",
    },
    "perf.summary": {
        "ru": "Оценка производительности: {score}/100 — узких мест: {n} (критических: {critical})",
        "en": "Performance score: {score}/100 — bottlenecks: {n} (critical: {critical})",
    },
    # --- problem report ---------------------------------------------------------
    "problems.none": {"ru": "Проблем не обнаружено", "en": "No problems found"},
    "problems.summary": {
        "ru": "Обнаружено проблем: {total} (критических: {critical}, автоисправимых: {fixable})",
        "en": "Problems found: {total} (critical: {critical}, auto-fixable: {fixable})",
    },
    "problem.logs_critical": {
        "ru": "Критических записей в системных журналах: {n}",
        "en": "Critical entries in system logs: {n}",
    },
    "problem.logs_critical.desc": {
        "ru": "Проанализировано источников: {sources}. Примеры: {sample}",
        "en": "Sources analysed: {sources}. Examples: {sample}",
    },
    "problem.logs_warnings": {
        "ru": "Предупреждений в системных журналах: {n}",
        "en": "Warnings in system logs: {n}",
    },
    "problem.logs_warnings.desc": {
        "ru": "Рекомендуется детальный анализ системных журналов",
        "en": "A detailed review of the system logs is recommended",
    },
    "problem.smart_failing": {
        "ru": "Диск {model} неисправен (S.M.A.R.T.)",
        "en": "Disk {model} is failing (S.M.A.R.T.)",
    },
    "problem.smart_failing.desc": {
        "ru": "Самодиагностика диска провалена — срочно сделайте резервную копию данных и замените диск",
        "en": "The drive failed its self-assessment — back up your data now and replace the drive",
    },
    "problem.smart_attr": {
        "ru": "S.M.A.R.T.: атрибут {name} ниже порога ({model})",
        "en": "S.M.A.R.T.: attribute {name} is below its threshold ({model})",
    },
    "problem.smart_attr.desc": {
        "ru": "Значение {value} при пороге {threshold}, исходное значение: {raw}",
        "en": "Value {value} against threshold {threshold}, raw value: {raw}",
    },
    "problem.partition_full": {
        "ru": "Раздел {device} почти полон ({v:.0f}%)",
        "en": "Partition {device} is almost full ({v:.0f}%)",
    },
    "problem.partition_full.desc": {
        "ru": "Очистите временные файлы, чтобы освободить место",
        "en": "Clean temporary files to free up space",
    },
    "problem.malware": {"ru": "Обнаружено вредоносное ПО: {signature}", "en": "Malware found: {signature}"},
    "problem.malware.desc": {"ru": "Файл: {path}", "en": "File: {path}"},
    # --- health dashboard -------------------------------------------------------
    "health.verdict.good": {"ru": "Компьютер в порядке", "en": "The PC is in good shape"},
    "health.verdict.warning": {"ru": "Есть на что обратить внимание", "en": "A few things need attention"},
    "health.verdict.serious": {"ru": "Есть серьёзные проблемы", "en": "There are serious problems"},
    "health.verdict.critical": {"ru": "Требуется срочное вмешательство", "en": "Urgent action required"},
    "health.status.good": {"ru": "Норма", "en": "Good"},
    "health.status.warning": {"ru": "Внимание", "en": "Warning"},
    "health.status.serious": {"ru": "Серьёзно", "en": "Serious"},
    "health.status.critical": {"ru": "Критично", "en": "Critical"},
    "health.status.unknown": {"ru": "Нет данных", "en": "No data"},
    "health.cpu": {"ru": "Процессор", "en": "Processor"},
    "health.memory": {"ru": "Память", "en": "Memory"},
    "health.disk": {"ru": "Диск", "en": "Disk"},
    "health.gpu": {"ru": "Видеокарта", "en": "Graphics"},
    "health.board": {"ru": "Плата и BIOS", "en": "Board and BIOS"},
    "health.os": {"ru": "Система", "en": "System"},
    "health.network": {"ru": "Сеть", "en": "Network"},
    "health.security": {"ru": "Безопасность", "en": "Security"},
    "health.m.temp": {"ru": "Температура", "en": "Temperature"},
    "health.m.load": {"ru": "Загрузка", "en": "Load"},
    "health.m.used": {"ru": "Занято", "en": "Used"},
    "health.m.swap": {"ru": "Подкачка", "en": "Swap"},
    "health.f.cores": {"ru": "Ядра / потоки", "en": "Cores / threads"},
    "health.f.freq": {"ru": "Частота", "en": "Frequency"},
    "health.f.freq.value": {"ru": "{cur:.0f} МГц (макс. {max:.0f})", "en": "{cur:.0f} MHz (max {max:.0f})"},
    "health.f.total": {"ru": "Всего", "en": "Total"},
    "health.f.modules": {"ru": "Модули", "en": "Modules"},
    "health.f.max": {"ru": "Максимум платы", "en": "Board maximum"},
    "health.f.type": {"ru": "Тип", "en": "Type"},
    "health.f.size": {"ru": "Объём", "en": "Capacity"},
    "health.f.hours": {"ru": "Наработка", "en": "Power-on time"},
    "health.f.hours.value": {"ru": "{h} ч (≈ {y:.1f} г.)", "en": "{h} h (≈ {y:.1f} y)"},
    "health.f.smart": {"ru": "S.M.A.R.T.", "en": "S.M.A.R.T."},
    "health.smart.ok": {"ru": "исправен", "en": "healthy"},
    "health.smart.fail": {"ru": "сбой", "en": "failing"},
    "health.smart.unknown": {"ru": "нет данных", "en": "no data"},
    "health.f.vram": {"ru": "Видеопамять", "en": "Video memory"},
    "health.f.driver": {"ru": "Драйвер", "en": "Driver"},
    "health.f.bios": {"ru": "BIOS", "en": "BIOS"},
    "health.f.chassis": {"ru": "Корпус", "en": "Chassis"},
    "health.f.boot": {"ru": "Режим загрузки", "en": "Boot mode"},
    "health.f.os_none": {"ru": "ОС не обнаружена", "en": "No OS detected"},
    "health.f.internet": {"ru": "Интернет", "en": "Internet"},
    "health.f.gateway": {"ru": "Шлюз", "en": "Gateway"},
    "health.yes": {"ru": "есть", "en": "available"},
    "health.no": {"ru": "нет", "en": "unavailable"},
    "health.unit.mb": {"ru": "МБ", "en": "MB"},
    "health.unit.gb": {"ru": "ГБ", "en": "GB"},
    "health.security.clean": {"ru": "Угроз не обнаружено", "en": "No threats found"},
    "health.security.threats": {"ru": "Обнаружено угроз: {n}", "en": "Threats found: {n}"},
    "health.partition": {"ru": "Раздел {device}", "en": "Partition {device}"},
    "history.cpu_temp": {"ru": "Температура процессора", "en": "CPU temperature"},
    "history.gpu_temp": {"ru": "Температура видеокарты", "en": "GPU temperature"},
    "history.ram": {"ru": "Занятая память", "en": "Memory used"},
    "history.disk_temp": {"ru": "Температура диска {dev}", "en": "Disk {dev} temperature"},
    "history.realloc": {"ru": "Переназначенные секторы, {dev}", "en": "Reallocated sectors, {dev}"},
    "history.unit.sectors": {"ru": "шт.", "en": ""},
    "safety.unknown": {
        "ru": "Действие не найдено в правилах — применены умеренные ограничения",
        "en": "Action is not in the rules — moderate restrictions applied",
    },
    "safety.expert_only": {
        "ru": "Действие заблокировано — включите режим эксперта",
        "en": "Action blocked — enable expert mode",
    },
    "safety.danger": {"ru": "ОПАСНО (эксперт): {reason}", "en": "DANGER (expert): {reason}"},
    "safety.needs_level": {
        "ru": "операции высокого риска доступны только в режиме эксперта",
        "en": "high-risk operations are available only in expert mode",
    },
    "ai.unavailable": {
        "ru": "AI сейчас недоступен: нет локальной модели и не задан ключ OpenRouter. Диагностика, вкладки "
              "«Здоровье» и «Проблемы», исправления и журнал работают и без него. Чтобы включить AI-агента, "
              "откройте ⚙ Настройки и введите ключ OpenRouter.",
        "en": "AI is unavailable right now: there is no local model and no OpenRouter key. Diagnostics, the "
              "Health and Problems tabs, fixes and the journal work without it. To enable the AI agent, open "
              "⚙ Settings and enter an OpenRouter key.",
    },
    "demo.unknown": {"ru": "Неизвестный демо-сценарий", "en": "Unknown demo scenario"},
}


def t(key: str, lang: str = "ru", **fmt) -> str:
    """Translate *key* into *lang* (falls back to Russian, then to the key itself)."""
    entry = _MESSAGES.get(key)
    if entry is None:
        return key
    text = entry[lang] if lang in entry else entry["ru"]  # an empty translation is a valid one
    return text.format(**fmt) if fmt else text


def pick(value, lang: str = "ru") -> str:
    """Pick a language from a ``{"ru": ..., "en": ...}`` dict; plain strings pass through."""
    if isinstance(value, dict):
        return value.get(lang) or value.get("ru") or next(iter(value.values()), "")
    return value or ""
