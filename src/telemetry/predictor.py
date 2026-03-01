"""Failure prediction — trend analysis of telemetry data."""

import json
from dataclasses import dataclass, field

from src.core.logger import get_logger
from src.telemetry.collector import TelemetryCollector, TelemetryRecord

log = get_logger("telemetry.predictor")


@dataclass
class Prediction:
    component: str = ""
    risk: str = "low"  # low | medium | high | critical
    description: str = ""
    trend: str = ""  # stable | degrading | failing
    estimated_days: int | None = None  # estimated days until failure


@dataclass
class PredictionReport:
    predictions: list[Prediction] = field(default_factory=list)
    data_points: int = 0

    @property
    def summary(self) -> str:
        critical = sum(1 for p in self.predictions if p.risk == "critical")
        high = sum(1 for p in self.predictions if p.risk == "high")
        if critical:
            return f"ВНИМАНИЕ: {critical} компонент(ов) под угрозой отказа!"
        if high:
            return f"Обнаружено {high} компонент(ов) с повышенным риском отказа"
        return "Все компоненты в нормальном состоянии"


def predict(telemetry: TelemetryCollector, machine_id: str) -> PredictionReport:
    """Analyze telemetry history and predict component failures."""
    report = PredictionReport()
    history = telemetry.get_history(machine_id, limit=100)
    report.data_points = len(history)

    if len(history) < 2:
        return report

    _predict_disk_failure(history, report)
    _predict_thermal_issues(history, report)
    _predict_ram_degradation(history, report)
    return report


def _predict_disk_failure(history: list[TelemetryRecord], report: PredictionReport) -> None:
    """Predict disk failure based on S.M.A.R.T. status and temperature trends."""
    # Track per-disk health over time
    disk_health: dict[str, list[bool]] = {}
    disk_temps: dict[str, list[float]] = {}
    disk_poh: dict[str, list[int]] = {}

    for record in history:
        try:
            status = json.loads(record.smart_status) if record.smart_status else {}
            temps = json.loads(record.disk_temps) if record.disk_temps else {}
            hours = json.loads(record.power_on_hours) if record.power_on_hours else {}
        except json.JSONDecodeError:
            continue

        for dev, healthy in status.items():
            disk_health.setdefault(dev, []).append(healthy)
        for dev, temp in temps.items():
            if isinstance(temp, (int, float)):
                disk_temps.setdefault(dev, []).append(temp)
        for dev, h in hours.items():
            if isinstance(h, int):
                disk_poh.setdefault(dev, []).append(h)

    for dev, healths in disk_health.items():
        if not all(healths):
            report.predictions.append(Prediction(
                component=f"Disk {dev}",
                risk="critical",
                description=f"S.M.A.R.T. диска {dev} показывает сбои — замена необходима",
                trend="failing",
            ))
        elif len(healths) >= 3:
            report.predictions.append(Prediction(
                component=f"Disk {dev}",
                risk="low",
                description=f"Диск {dev} стабильно исправен",
                trend="stable",
            ))

    # Temperature trend analysis
    for dev, temps in disk_temps.items():
        if len(temps) >= 3:
            trend = _linear_trend(temps)
            if trend > 0.5:  # temperature rising > 0.5°C per session
                report.predictions.append(Prediction(
                    component=f"Disk {dev} temp",
                    risk="medium",
                    description=f"Температура диска {dev} растёт (тренд: +{trend:.1f}°C/сессию)",
                    trend="degrading",
                ))

    # Power-on hours check (HDD typically rated for 30k-50k hours)
    for dev, hours_list in disk_poh.items():
        if hours_list and hours_list[0] > 40000:
            report.predictions.append(Prediction(
                component=f"Disk {dev}",
                risk="high",
                description=f"Диск {dev} наработал {hours_list[0]} часов — приближается к пределу ресурса",
                trend="degrading",
                estimated_days=365,
            ))


def _predict_thermal_issues(history: list[TelemetryRecord], report: PredictionReport) -> None:
    """Predict thermal problems from CPU/GPU temperature trends."""
    cpu_temps = [r.cpu_temp for r in history if r.cpu_temp is not None]
    gpu_temps = [r.gpu_temp for r in history if r.gpu_temp is not None]

    if len(cpu_temps) >= 3:
        trend = _linear_trend(cpu_temps)
        avg = sum(cpu_temps) / len(cpu_temps)
        if trend > 1.0 or avg > 80:
            report.predictions.append(Prediction(
                component="CPU Temperature",
                risk="high" if avg > 80 else "medium",
                description=(
                    f"Средняя температура CPU: {avg:.0f}°C, тренд: {'+' if trend > 0 else ''}{trend:.1f}°C/сессию. "
                    "Рекомендуется замена термопасты и чистка системы охлаждения."
                ),
                trend="degrading" if trend > 0.5 else "stable",
            ))

    if len(gpu_temps) >= 3:
        avg = sum(gpu_temps) / len(gpu_temps)
        if avg > 85:
            report.predictions.append(Prediction(
                component="GPU Temperature",
                risk="high",
                description=f"Средняя температура GPU: {avg:.0f}°C — проверьте охлаждение",
                trend="degrading",
            ))


def _predict_ram_degradation(history: list[TelemetryRecord], report: PredictionReport) -> None:
    """Check for consistently high RAM usage suggesting upgrade need."""
    ram_usage = [r.ram_usage_pct for r in history if r.ram_usage_pct is not None]
    if len(ram_usage) >= 3:
        avg = sum(ram_usage) / len(ram_usage)
        if avg > 85:
            report.predictions.append(Prediction(
                component="RAM",
                risk="medium",
                description=f"Среднее использование ОЗУ: {avg:.0f}% — рекомендуется увеличение объёма",
                trend="stable",
            ))


def _linear_trend(values: list[float]) -> float:
    """Calculate simple linear regression slope (change per data point)."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator
