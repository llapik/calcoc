"""Configuration management for AI PC Repair & Optimizer."""

import os
from pathlib import Path

import yaml

from src.core import platform


_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_CONFIG_DIR = _ROOT_DIR / "config"


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge *override* into *base* recursively, returning a new dict."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Config:
    """Centralised access to every YAML config file."""

    def __init__(self, config_dir: str | Path | None = None):
        self.config_dir = Path(config_dir) if config_dir else _CONFIG_DIR
        self._cache: dict[str, dict] = {}
        self.settings = self._load("settings.yaml")
        self.models = self._load("models.yaml")
        self.safety_rules = self._load("safety_rules.yaml")
        self._apply_env_overrides()

    # ------------------------------------------------------------------
    def _load(self, filename: str) -> dict:
        path = self.config_dir / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        else:
            data = {}
        self._cache[filename] = data
        return data

    # ------------------------------------------------------------------
    def _apply_env_overrides(self) -> None:
        """Allow critical settings to be overridden via environment."""
        if api_key := os.environ.get("OPENROUTER_API_KEY"):
            self.settings.setdefault("openrouter", {})["api_key"] = api_key
        if backend := os.environ.get("AI_BACKEND"):
            self.settings.setdefault("ai", {})["backend"] = backend
        if lang := os.environ.get("APP_LANGUAGE"):
            self.settings.setdefault("app", {})["language"] = lang

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    @property
    def app_name(self) -> str:
        return self.settings.get("app", {}).get("name", "AI PC Repair & Optimizer")

    @property
    def language(self) -> str:
        return self.settings.get("app", {}).get("language", "ru")

    @property
    def expert_mode(self) -> bool:
        return self.settings.get("app", {}).get("expert_mode", False)

    @property
    def ai_backend(self) -> str:
        return self.settings.get("ai", {}).get("backend", "llama")

    @property
    def web_host(self) -> str:
        return self.settings.get("app", {}).get("web_host", "127.0.0.1")

    @property
    def web_port(self) -> int:
        return int(self.settings.get("app", {}).get("web_port", 8080))

    @property
    def openrouter_api_key(self) -> str:
        return self.settings.get("openrouter", {}).get("api_key", "")

    @property
    def openrouter_base_url(self) -> str:
        return self.settings.get("openrouter", {}).get(
            "base_url", "https://openrouter.ai/api/v1"
        )

    @property
    def openrouter_model(self) -> str:
        return self.settings.get("openrouter", {}).get(
            "default_model", "meta-llama/llama-3-8b-instruct"
        )

    @property
    def mode(self) -> str:
        """``desktop`` (inside a running OS) or ``rescue`` (booted from USB)."""
        return platform.run_mode()

    @property
    def data_dir(self) -> Path:
        """Root for journal, backups, telemetry and logs."""
        raw = self.settings.get("paths", {}).get("data_dir", "auto")
        return platform.default_data_dir() if raw in ("", "auto", None) else Path(raw)

    def _resolve(self, key: str) -> Path:
        raw = self.settings.get("paths", {}).get(key) or key
        p = Path(raw)
        return p if p.is_absolute() else self.data_dir / p

    def path(self, key: str) -> Path:
        """Return a directory from the ``paths`` section (relative to ``data_dir``), creating it."""
        p = self._resolve(key)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def file_path(self, key: str) -> Path:
        """Return a file path from the ``paths`` section, creating its parent directory."""
        p = self._resolve(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def knowledge_dir(self) -> Path:
        """User knowledge base if present, otherwise the one bundled with the app."""
        custom = self._resolve("knowledge_dir")
        if custom.is_dir() and any(custom.glob("*.json")):
            return custom
        return _ROOT_DIR / "data" / "knowledge"

    @property
    def demo_dir(self) -> Path:
        return _ROOT_DIR / "data" / "demo"
