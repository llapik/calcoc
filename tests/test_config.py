"""Tests for configuration management."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from src.core.config import Config


@pytest.fixture
def config_dir(tmp_path):
    """Create a temporary config directory with test settings."""
    settings = {
        "app": {"name": "Test App", "version": "0.0.1", "language": "en", "web_port": 9999},
        "ai": {"backend": "none"},
        "openrouter": {"api_key": "", "base_url": "https://openrouter.ai/api/v1"},
        "paths": {"backup_dir": str(tmp_path / "backups"), "logs_dir": str(tmp_path / "logs")},
        "safety": {"require_confirmation": True, "max_risk_level": "yellow"},
    }
    models = {"models": [{"name": "none", "min_ram_mb": 0, "max_ram_mb": 999999, "file": None}]}
    safety = {"risk_levels": {"green": {"requires_confirmation": False}}, "actions": {}}

    for name, data in [("settings.yaml", settings), ("models.yaml", models), ("safety_rules.yaml", safety)]:
        with open(tmp_path / name, "w") as fh:
            yaml.dump(data, fh)

    return tmp_path


def test_config_loads(config_dir):
    config = Config(config_dir)
    assert config.app_name == "Test App"
    assert config.language == "en"
    assert config.web_port == 9999
    assert config.ai_backend == "none"


def test_config_env_override(config_dir, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    monkeypatch.setenv("AI_BACKEND", "openrouter")
    config = Config(config_dir)
    assert config.openrouter_api_key == "test-key-123"
    assert config.ai_backend == "openrouter"


def test_config_path_creates_dir(config_dir):
    config = Config(config_dir)
    p = config.path("backup_dir")
    assert p.exists()
    assert p.is_dir()


def test_config_defaults_on_missing_file(tmp_path):
    """Config should provide defaults when files are missing."""
    config = Config(tmp_path)
    assert config.app_name == "AI PC Repair & Optimizer"
    assert config.language == "ru"
    assert config.web_port == 8080
