"""Upgrade advisor — identify bottlenecks and recommend compatible components."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.core.logger import get_logger
from src.diagnostics.collector import SystemSnapshot

log = get_logger("upgrade.advisor")


@dataclass
class UpgradeRecommendation:
    component: str = ""  # ram | ssd | cpu | gpu
    priority: int = 0  # 1 = highest
    current: str = ""
    recommended: str = ""
    reason: str = ""
    expected_impact: str = ""
    estimated_cost: str = ""


@dataclass
class UpgradeReport:
    bottlenecks: list[str] = field(default_factory=list)
    recommendations: list[UpgradeRecommendation] = field(default_factory=list)
    overall_assessment: str = ""

    def to_text(self) -> str:
        lines = ["=== Рекомендации по апгрейду ===", ""]
        if self.overall_assessment:
            lines.append(self.overall_assessment)
            lines.append("")

        if self.bottlenecks:
            lines.append("Узкие места:")
            for b in self.bottlenecks:
                lines.append(f"  • {b}")
            lines.append("")

        if self.recommendations:
            lines.append("Рекомендации (в порядке приоритета):")
            for rec in sorted(self.recommendations, key=lambda r: r.priority):
                lines.append(f"\n  {rec.priority}. {rec.component.upper()}")
                lines.append(f"     Текущее: {rec.current}")
                lines.append(f"     Рекомендуется: {rec.recommended}")
                lines.append(f"     Причина: {rec.reason}")
                lines.append(f"     Ожидаемый эффект: {rec.expected_impact}")
                if rec.estimated_cost:
                    lines.append(f"     Примерная стоимость: {rec.estimated_cost}")
        else:
            lines.append("Система сбалансирована, срочных апгрейдов не требуется.")

        return "\n".join(lines)


def analyze(snapshot: SystemSnapshot, components_db_path: str | None = None) -> UpgradeReport:
    """Analyze system snapshot and generate upgrade recommendations."""
    report = UpgradeReport()
    priority = 1

    # Load components database if available
    components_db = _load_components_db(components_db_path) if components_db_path else {}

    # --- SSD upgrade (highest impact for most users) ---
    if snapshot.disk:
        has_hdd_boot = False
        for d in snapshot.disk.devices:
            if d.type == "HDD":
                # Check if this is the boot disk
                for part in d.partitions:
                    if part.mount_point in ("/", "C:\\", "/mnt/windows"):
                        has_hdd_boot = True
                        break
                if has_hdd_boot:
                    break

        if has_hdd_boot:
            report.bottlenecks.append("Системный диск — HDD (медленная загрузка и работа)")
            report.recommendations.append(UpgradeRecommendation(
                component="ssd",
                priority=priority,
                current="HDD (системный диск)",
                recommended="SSD SATA 240-512 ГБ или NVMe M.2 (если поддерживается)",
                reason="Замена HDD на SSD — наиболее ощутимый апгрейд для любого ПК",
                expected_impact="Загрузка ОС: 60s → 15s, общая отзывчивость: +300-500%",
                estimated_cost="2000-5000 руб.",
            ))
            priority += 1

    # --- RAM upgrade ---
    if snapshot.memory:
        mem = snapshot.memory
        if mem.total_mb < 4096:
            report.bottlenecks.append(f"Мало ОЗУ: {mem.total_mb} МБ")
            target = "8 ГБ"
            report.recommendations.append(UpgradeRecommendation(
                component="ram",
                priority=priority,
                current=f"{mem.total_mb} МБ",
                recommended=f"{target} ({mem.slots[0].type if mem.slots else 'DDR'})",
                reason="Недостаточно памяти для комфортной работы",
                expected_impact="Уменьшение использования подкачки, улучшение многозадачности",
                estimated_cost="1500-3000 руб.",
            ))
            priority += 1
        elif mem.total_mb < 8192 and mem.usage_percent > 70:
            report.bottlenecks.append(f"ОЗУ загружена на {mem.usage_percent}% ({mem.total_mb} МБ)")
            report.recommendations.append(UpgradeRecommendation(
                component="ram",
                priority=priority,
                current=f"{mem.total_mb} МБ ({mem.usage_percent}% загрузка)",
                recommended=f"16 ГБ ({mem.slots[0].type if mem.slots else 'DDR'})",
                reason="Высокая загрузка памяти приводит к замедлению",
                expected_impact="Улучшение производительности при многозадачности",
                estimated_cost="2000-4000 руб.",
            ))
            priority += 1

        # Check for single-channel memory
        if len(mem.slots) == 1 and mem.total_mb >= 4096:
            report.recommendations.append(UpgradeRecommendation(
                component="ram",
                priority=priority,
                current=f"1x {mem.slots[0].size_mb} МБ (одноканальный режим)",
                recommended=f"2x {mem.slots[0].size_mb} МБ (двухканальный режим)",
                reason="Двухканальный режим увеличивает пропускную способность памяти",
                expected_impact="Ускорение операций с памятью на 10-30%",
                estimated_cost="1500-3000 руб.",
            ))
            priority += 1

    # --- CPU upgrade ---
    if snapshot.cpu:
        cpu = snapshot.cpu
        if cpu.cores_physical <= 2 and cpu.frequency_mhz < 2000:
            report.bottlenecks.append(f"Устаревший CPU: {cpu.model}")
            report.recommendations.append(UpgradeRecommendation(
                component="cpu",
                priority=priority,
                current=f"{cpu.model} ({cpu.cores_physical}C/{cpu.cores_logical}T, {cpu.frequency_mhz:.0f} МГц)",
                recommended="Современный 4+ ядерный процессор",
                reason="Процессор ограничивает производительность системы",
                expected_impact="Значительное ускорение всех задач",
                estimated_cost="5000-15000 руб. (с материнской платой)",
            ))
            priority += 1

    # --- Disk health urgent ---
    if snapshot.disk:
        for d in snapshot.disk.devices:
            if d.smart_healthy is False:
                report.bottlenecks.append(f"Диск {d.model} неисправен!")
                report.recommendations.insert(0, UpgradeRecommendation(
                    component="ssd",
                    priority=0,  # highest
                    current=f"{d.model} — S.M.A.R.T. FAILING",
                    recommended="Срочная замена диска + восстановление данных",
                    reason="Диск может выйти из строя в любой момент",
                    expected_impact="Предотвращение потери данных",
                    estimated_cost="2000-8000 руб.",
                ))

    # Overall assessment
    if not report.recommendations:
        report.overall_assessment = "Система в хорошем состоянии, срочных апгрейдов не требуется."
    elif len(report.bottlenecks) >= 3:
        report.overall_assessment = (
            "Система имеет множество узких мест. Рекомендуется комплексный апгрейд "
            "или рассмотрение замены ПК целиком."
        )
    else:
        report.overall_assessment = (
            f"Найдено {len(report.bottlenecks)} узких мест. "
            "Следуйте рекомендациям в порядке приоритета для максимального эффекта."
        )

    return report


def _load_components_db(path: str | None) -> dict:
    """Load local hardware components price database."""
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        log.debug("Components DB not available: %s", exc)
        return {}
