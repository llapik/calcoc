"""Configuration management for AI PC Repair & Optimizer."""

import os
from pathlib import Path

import yaml


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


_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class Config:
    """Centralised access to every YAML config file."""

    def __init__(self, config_dir: str | Path | None = None):
        if config_dir is not None:
            resolved = Path(config_dir).resolve()
            # Only allow config dirs that are subdirectories of the repo root or
            # absolute paths under recognised safe prefixes (e.g. /mnt, /media, /run).
            _safe_prefixes = (
                str(_ROOT_DIR),
                "/mnt/", "/media/", "/run/", "/etc/calcoc", "/tmp/",
            )
            if not any(str(resolved).startswith(p) for p in _safe_prefixes):
                raise ValueError(
                    f"Unsafe config directory: {config_dir!r}. "
                    "Must be inside the repo root or a recognised mount path."
                )
            self.config_dir = resolved
        else:
            self.config_dir = _CONFIG_DIR
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
        """Return the OpenRouter base URL, refusing any non-OpenRouter override.

        Hard-coding the allowed host prevents SSRF attacks where a malicious
        settings.yaml redirects API calls (and the Bearer token) to a third-party
        server.
        """
        url = self.settings.get("openrouter", {}).get("base_url", _OPENROUTER_BASE_URL)
        if not str(url).startswith("https://openrouter.ai/"):
            return _OPENROUTER_BASE_URL
        return url

    @property
    def openrouter_model(self) -> str:
        return self.settings.get("openrouter", {}).get(
            "default_model", "meta-llama/llama-3-8b-instruct"
        )

    def path(self, key: str) -> Path:
        """Return a path from the ``paths`` section, creating it if needed.

        Falls back to /var/lib/calcoc/<key> (root-owned, mode 700) instead of
        /tmp to avoid world-writable default directories.
        """
        raw = self.settings.get("paths", {}).get(key, f"/var/lib/calcoc/{key}")
        p = Path(raw)
        p.mkdir(parents=True, exist_ok=True, mode=0o700)
        return p
