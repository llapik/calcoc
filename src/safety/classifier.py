"""Safety classifier — risk assessment and action gating."""

from dataclasses import dataclass

from src.core.config import Config
from src.core.logger import get_logger

log = get_logger("safety.classifier")


@dataclass
class SafetyVerdict:
    action: str
    risk_level: str  # green | yellow | red | black
    allowed: bool
    reason: str
    requires_confirmation: bool
    requires_backup: bool
    label: str = ""


class SafetyClassifier:
    """Evaluate whether an action is permitted under current safety settings."""

    def __init__(self, config: Config):
        self.config = config
        self.rules = config.safety_rules
        self._risk_levels = self.rules.get("risk_levels", {})
        self._actions = self.rules.get("actions", {})

    def check(self, action: str) -> SafetyVerdict:
        """Check if an action is allowed and what precautions are needed."""
        action_def = self._actions.get(action)
        if action_def is None:
            # Unknown action — treat as yellow by default
            return SafetyVerdict(
                action=action,
                risk_level="yellow",
                allowed=True,
                reason="Действие не найдено в правилах — применены умеренные ограничения",
                requires_confirmation=True,
                requires_backup=True,
            )

        risk = action_def.get("risk", "yellow")
        level_def = self._risk_levels.get(risk, {})
        max_allowed = self.config.settings.get("safety", {}).get("max_risk_level", "yellow")
        expert_mode = self.config.expert_mode

        # Determine if action is allowed
        allowed = True
        reason = action_def.get("description", "")

        if risk == "black":
            if not expert_mode:
                allowed = False
                reason = action_def.get(
                    "blocked_reason",
                    "Действие заблокировано — включите режим эксперта",
                )
            else:
                reason = f"ОПАСНО (эксперт): {reason}"

        elif risk == "red" and max_allowed not in ("red", "black"):
            if not expert_mode:
                allowed = False
                reason = f"Действие требует повышения уровня допуска (текущий: {max_allowed})"

        requires_confirmation = level_def.get("requires_confirmation", True)
        requires_backup = level_def.get("auto_backup", True)
        label = level_def.get("label", risk)

        if self.config.settings.get("safety", {}).get("require_confirmation", True):
            requires_confirmation = requires_confirmation or risk != "green"

        verdict = SafetyVerdict(
            action=action,
            risk_level=risk,
            allowed=allowed,
            reason=reason,
            requires_confirmation=requires_confirmation,
            requires_backup=requires_backup,
            label=label,
        )

        log.info("Safety check: %s -> %s (allowed=%s)", action, risk, allowed)
        return verdict

    def get_risk_color(self, risk_level: str) -> str:
        """Return a CSS color for the risk level."""
        colors = {
            "green": "#28a745",
            "yellow": "#ffc107",
            "red": "#dc3545",
            "black": "#343a40",
        }
        return colors.get(risk_level, "#6c757d")

    def list_actions(self) -> list[dict]:
        """Return all known actions with their risk levels."""
        result = []
        for action_name, action_def in self._actions.items():
            risk = action_def.get("risk", "yellow")
            result.append({
                "action": action_name,
                "risk": risk,
                "description": action_def.get("description", ""),
                "color": self.get_risk_color(risk),
            })
        return result
