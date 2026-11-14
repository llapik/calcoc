"""Failure prediction — trend analysis of telemetry history.

Works on a chronological list of :class:`TelemetryRecord` (oldest first). Trends are measured
against real time (per 30 days), not per scan, so irregular scan intervals do not distort them.
Nothing here claims a date of failure: the output says what is growing and how fast.
"""

from dataclasses import dataclass, field

from src.core.logger import get_logger
from src.telemetry.collector import TelemetryCollector, TelemetryRecord

log = get_logger("telemetry.predictor")

_DAY = 86400.0
_MONTH = 30 * _DAY
_HDD_WEAR_HOURS = 40000  # typical desktop HDDs are designed for roughly 30-50 thousand hours

_MESSAGES = {
    "smart_failing": {
        "ru": "Диск {dev}: S.M.A.R.T. сообщает о сбое — нужна замена, данные под угрозой",
        "en": "Disk {dev}: S.M.A.R.T. reports failure — replace it, data is at risk",
    },
    "realloc_growing": {
        "ru": "Диск {dev}: переназначенных секторов уже {now} (было {first}), прирост ≈ {rate:.0f} за 30 дней. "
              "Поверхность разрушается — скопируйте данные и замените диск",
        "en": "Disk {dev}: {now} reallocated sectors (was {first}), growing by ≈ {rate:.0f} per 30 days. "
              "The surface is deteriorating — copy your data and replace the drive",
    },
    "realloc_present": {
        "ru": "Диск {dev}: {now} переназначенных секторов, за время наблюдения число не растёт",
        "en": "Disk {dev}: {now} reallocated sectors, the count has not grown while observed",
    },
    "pending_growing": {
        "ru": "Диск {dev}: нестабильных секторов {now} (было {first}) — диск теряет читаемые области",
        "en": "Disk {dev}: {now} pending sectors (was {first}) — the drive is losing readable areas",
    },
    "disk_temp_rising": {
        "ru": "Диск {dev}: температура растёт на {rate:.1f} °C за 30 дней (сейчас {now:.0f} °C)",
        "en": "Disk {dev}: temperature is rising by {rate:.1f} °C per 30 days (now {now:.0f} °C)",
    },
    "disk_worn": {
        "ru": "Диск {dev}: наработка {hours} ч — ресурс близок к расчётному, держите резервную копию",
        "en": "Disk {dev}: {hours} power-on hours — close to design life, keep a backup",
    },
    "cpu_temp_rising": {
        "ru": "Процессор: температура растёт на {rate:.1f} °C за 30 дней (сейчас {now:.0f} °C) — "
              "проверьте охлаждение и фоновую нагрузку",
        "en": "CPU: temperature is rising by {rate:.1f} °C per 30 days (now {now:.0f} °C) — "
              "check the cooling and background load",
    },
    "cpu_temp_high": {
        "ru": "Процессор: средняя температура {avg:.0f} °C за время наблюдения — охлаждение не справляется",
        "en": "CPU: average temperature {avg:.0f} °C while observed — the cooling cannot keep up",
    },
    "gpu_temp_high": {
        "ru": "Видеокарта: средняя температура {avg:.0f} °C — проверьте охлаждение",
        "en": "GPU: average temperature {avg:.0f} °C — check its cooling",
    },
    "ram_pressure": {
        "ru": "Память: в среднем занято {avg:.0f}% — системе постоянно не хватает ОЗУ",
        "en": "Memory: {avg:.0f}% used on average — the system is constantly short of RAM",
    },
    "summary_critical": {
        "ru": "Под угрозой отказа: {n}", "en": "At risk of failure: {n}",
    },
    "summary_high": {
        "ru": "Компонентов с повышенным риском: {n}", "en": "Components at elevated risk: {n}",
    },
    "summary_medium": {
        "ru": "Тенденций, за которыми стоит следить: {n}", "en": "Trends worth watching: {n}",
    },
    "summary_ok": {
        "ru": "Тревожных тенденций не обнаружено", "en": "No worrying trends found",
    },
    "summary_few": {
        "ru": "Для прогноза нужно хотя бы два замера в разные дни", "en": "A forecast needs at least two scans",
    },
}


def _msg(key: str, lang: str, **fmt) -> str:
    entry = _MESSAGES[key]
    return (entry.get(lang) or entry["ru"]).format(**fmt)


@dataclass
class Prediction:
    component: str = ""   # cpu | gpu | memory | disk:<device>
    risk: str = "low"     # low | medium | high | critical
    description: str = ""
    trend: str = ""       # stable | degrading | failing
    kind: str = ""        # machine-readable finding type


@dataclass
class PredictionReport:
    predictions: list[Prediction] = field(default_factory=list)
    data_points: int = 0
    lang: str = "ru"

    @property
    def summary(self) -> str:
        if self.data_points < 2:
            return _msg("summary_few", self.lang)
        critical = sum(1 for p in self.predictions if p.risk == "critical")
        high = sum(1 for p in self.predictions if p.risk == "high")
        if critical:
            return _msg("summary_critical", self.lang, n=critical)
        if high:
            return _msg("summary_high", self.lang, n=high)
        if self.predictions:
            return _msg("summary_medium", self.lang, n=len(self.predictions))
        return _msg("summary_ok", self.lang)


def predict(telemetry: TelemetryCollector, machine_id: str, lang: str = "ru") -> PredictionReport:
    """Analyze stored telemetry for one machine."""
    history = telemetry.get_history(machine_id, limit=200)  # newest first
    return predict_records(history[::-1], lang)


def predict_records(history: list[TelemetryRecord], lang: str = "ru") -> PredictionReport:
    """Analyze a chronological (oldest first) telemetry history."""
    report = PredictionReport(data_points=len(history), lang=lang)
    if len(history) < 2:
        return report
    _disks(history, report)
    _thermals(history, report)
    _memory(history, report)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    report.predictions.sort(key=lambda p: order.get(p.risk, 9))
    return report


def _series(
    history: list[TelemetryRecord], column: str, key: str | None = None,
) -> dict[str, list[tuple[float, float]]]:
    """Per-device ``[(timestamp, value)]`` from a JSON column (*key* picks a nested value)."""
    out: dict[str, list[tuple[float, float]]] = {}
    for r in history:
        for dev, value in r.per_disk(column).items():
            if key is not None:
                value = value.get(key) if isinstance(value, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out.setdefault(dev, []).append((r.timestamp, float(value)))
    return out


def _disks(history: list[TelemetryRecord], report: PredictionReport) -> None:
    lang = report.lang
    add = report.predictions.append

    failing = {dev for r in history for dev, ok in r.per_disk("smart_status").items() if ok is False}
    for dev in sorted(failing):
        add(Prediction(f"disk:{dev}", "critical", _msg("smart_failing", lang, dev=dev), "failing", "smart_failing"))

    for dev, points in _series(history, "smart_attrs", "5").items():
        first, now = points[0][1], points[-1][1]
        if now <= 0:
            continue
        rate = slope_per_month(points)
        if now > first and rate > 0:
            add(Prediction(
                f"disk:{dev}", "critical" if dev in failing or rate >= 50 else "high",
                _msg("realloc_growing", lang, dev=dev, now=int(now), first=int(first), rate=rate),
                "failing", "realloc_growing",
            ))
        elif dev not in failing:
            add(Prediction(f"disk:{dev}", "medium", _msg("realloc_present", lang, dev=dev, now=int(now)),
                           "stable", "realloc_present"))

    for dev, points in _series(history, "smart_attrs", "197").items():
        first, now = points[0][1], points[-1][1]
        if now > first:
            add(Prediction(f"disk:{dev}", "high",
                           _msg("pending_growing", lang, dev=dev, now=int(now), first=int(first)),
                           "degrading", "pending_growing"))

    for dev, points in _series(history, "disk_temps").items():
        rate = slope_per_month(points)
        if len(points) >= 3 and rate > 1.0 and _spans(points, 7):
            add(Prediction(f"disk:{dev}", "medium",
                           _msg("disk_temp_rising", lang, dev=dev, rate=rate, now=points[-1][1]),
                           "degrading", "disk_temp_rising"))

    for dev, points in _series(history, "power_on_hours").items():
        hours = points[-1][1]
        if hours > _HDD_WEAR_HOURS and dev not in failing:
            add(Prediction(f"disk:{dev}", "medium", _msg("disk_worn", lang, dev=dev, hours=int(hours)),
                           "degrading", "disk_worn"))


def _thermals(history: list[TelemetryRecord], report: PredictionReport) -> None:
    lang = report.lang
    cpu = [(r.timestamp, r.cpu_temp) for r in history if r.cpu_temp is not None]
    if len(cpu) >= 3:
        avg = sum(v for _, v in cpu) / len(cpu)
        rate = slope_per_month(cpu)
        if rate > 1.0 and _spans(cpu, 7):
            report.predictions.append(Prediction(
                "cpu", "high" if cpu[-1][1] > 80 else "medium",
                _msg("cpu_temp_rising", lang, rate=rate, now=cpu[-1][1]), "degrading", "cpu_temp_rising",
            ))
        elif avg > 80:
            report.predictions.append(Prediction(
                "cpu", "high", _msg("cpu_temp_high", lang, avg=avg), "stable", "cpu_temp_high",
            ))

    gpu = [r.gpu_temp for r in history if r.gpu_temp is not None]
    if len(gpu) >= 3 and sum(gpu) / len(gpu) > 85:
        report.predictions.append(Prediction(
            "gpu", "high", _msg("gpu_temp_high", lang, avg=sum(gpu) / len(gpu)), "degrading", "gpu_temp_high",
        ))


def _memory(history: list[TelemetryRecord], report: PredictionReport) -> None:
    ram = [r.ram_usage_pct for r in history if r.ram_usage_pct is not None]
    if len(ram) >= 3 and sum(ram) / len(ram) > 85:
        report.predictions.append(Prediction(
            "memory", "medium", _msg("ram_pressure", report.lang, avg=sum(ram) / len(ram)), "stable", "ram_pressure",
        ))


def _spans(points: list[tuple[float, float]], days: float) -> bool:
    """True if the observations cover at least *days* — shorter runs are noise, not a trend."""
    return points[-1][0] - points[0][0] >= days * _DAY


def slope_per_month(points: list[tuple[float, float]]) -> float:
    """Least-squares slope of ``(timestamp, value)`` points, in value units per 30 days."""
    n = len(points)
    if n < 2:
        return 0.0
    t_mean = sum(ts for ts, _ in points) / n
    v_mean = sum(v for _, v in points) / n
    denominator = sum((ts - t_mean) ** 2 for ts, _ in points)
    if denominator == 0:
        return 0.0
    return sum((ts - t_mean) * (v - v_mean) for ts, v in points) / denominator * _MONTH


def _linear_trend(values: list[float]) -> float:
    """Least-squares slope per data point for evenly spaced values."""
    return slope_per_month([(i * _MONTH, v) for i, v in enumerate(values)])
