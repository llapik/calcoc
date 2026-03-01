"""Tests for safety classifier."""

import pytest
import yaml

from src.core.config import Config
from src.safety.classifier import SafetyClassifier


@pytest.fixture
def config_with_rules(tmp_path):
    safety_rules = {
        "risk_levels": {
            "green": {"label": "Safe", "requires_confirmation": False, "auto_backup": False},
            "yellow": {"label": "Moderate", "requires_confirmation": True, "auto_backup": True},
            "red": {"label": "High Risk", "requires_confirmation": True, "auto_backup": True},
            "black": {"label": "Forbidden", "requires_confirmation": True, "auto_backup": True, "expert_only": True},
        },
        "actions": {
            "read_smart": {"risk": "green", "description": "Read SMART data"},
            "fix_filesystem": {"risk": "yellow", "description": "Fix filesystem errors"},
            "fix_bootloader": {"risk": "red", "description": "Fix bootloader"},
            "flash_bios": {"risk": "black", "description": "Flash BIOS", "blocked_reason": "Too dangerous"},
        },
    }
    settings = {
        "app": {"expert_mode": False},
        "safety": {"require_confirmation": True, "max_risk_level": "yellow"},
    }
    with open(tmp_path / "safety_rules.yaml", "w") as fh:
        yaml.dump(safety_rules, fh)
    with open(tmp_path / "settings.yaml", "w") as fh:
        yaml.dump(settings, fh)
    with open(tmp_path / "models.yaml", "w") as fh:
        yaml.dump({"models": []}, fh)
    return Config(tmp_path)


def test_green_action_allowed(config_with_rules):
    classifier = SafetyClassifier(config_with_rules)
    verdict = classifier.check("read_smart")
    assert verdict.allowed is True
    assert verdict.risk_level == "green"
    assert verdict.requires_backup is False


def test_yellow_action_needs_confirmation(config_with_rules):
    classifier = SafetyClassifier(config_with_rules)
    verdict = classifier.check("fix_filesystem")
    assert verdict.allowed is True
    assert verdict.risk_level == "yellow"
    assert verdict.requires_confirmation is True
    assert verdict.requires_backup is True


def test_red_action_blocked_without_expert(config_with_rules):
    classifier = SafetyClassifier(config_with_rules)
    verdict = classifier.check("fix_bootloader")
    assert verdict.allowed is False
    assert verdict.risk_level == "red"


def test_black_action_blocked_without_expert(config_with_rules):
    classifier = SafetyClassifier(config_with_rules)
    verdict = classifier.check("flash_bios")
    assert verdict.allowed is False
    assert verdict.risk_level == "black"


def test_black_action_allowed_in_expert_mode(config_with_rules):
    config_with_rules.settings["app"]["expert_mode"] = True
    classifier = SafetyClassifier(config_with_rules)
    verdict = classifier.check("flash_bios")
    assert verdict.allowed is True
    assert verdict.requires_confirmation is True


def test_unknown_action_defaults_to_yellow(config_with_rules):
    classifier = SafetyClassifier(config_with_rules)
    verdict = classifier.check("unknown_action_xyz")
    assert verdict.risk_level == "yellow"
    assert verdict.allowed is True
    assert verdict.requires_confirmation is True


def test_risk_colors(config_with_rules):
    classifier = SafetyClassifier(config_with_rules)
    assert classifier.get_risk_color("green") == "#28a745"
    assert classifier.get_risk_color("red") == "#dc3545"
    assert classifier.get_risk_color("black") == "#343a40"
