"""OpenRouter API backend for cloud-based AI inference."""

import json
from typing import Generator

import requests

from src.core.logger import get_logger

log = get_logger("ai.openrouter")


class OpenRouterBackend:
    """Cloud AI backend via OpenRouter API (https://openrouter.ai)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "meta-llama/llama-3-8b-instruct",
        fallback_models: list[str] | None = None,
    ):
        # Keep only a short masked suffix for diagnostics; never log the full key
        self._key_hint = f"...{api_key[-4:]}" if len(api_key) >= 8 else "***"
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.fallback_models = fallback_models or []
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/calcoc",
            "X-Title": "AI PC Repair & Optimizer",
        })

    @property
    def is_available(self) -> bool:
        return bool(self._session.headers.get("Authorization", "").removeprefix("Bearer "))

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """Send a chat completion request to OpenRouter."""
        target_model = model or self.default_model
        models_to_try = [target_model] + self.fallback_models

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        last_error = None
        for m in models_to_try:
            try:
                return self._call(messages, m, temperature, max_tokens)
            except Exception as exc:
                log.warning("Model %s failed: %s", m, exc)
                last_error = exc

        raise RuntimeError(f"All models failed. Last error: {last_error}")

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> Generator[str, None, None]:
        """Stream a chat completion from OpenRouter."""
        target_model = model or self.default_model

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            resp = self._session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        yield token
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        except Exception as exc:
            log.error("OpenRouter stream failed: %s", exc)
            raise

    def _call(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        log.debug("Requesting %s via OpenRouter (key %s)", model, self._key_hint)
        resp = self._session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        log.debug("Response received (%d chars)", len(content))
        return content.strip()

    def list_models(self) -> list[dict]:
        """Fetch the list of available models from OpenRouter."""
        try:
            resp = self._session.get(f"{self.base_url}/models", timeout=30)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as exc:
            log.warning("Failed to list OpenRouter models: %s", exc)
            return []
