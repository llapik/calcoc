"""Unified AI engine — abstracts over local (llama.cpp) and cloud (OpenRouter) backends."""

from pathlib import Path
from typing import Generator

from src.core.config import Config
from src.core.logger import get_logger
from src.ai.llama_backend import LlamaBackend
from src.ai.openrouter import OpenRouterBackend
from src.ai.model_selector import select_model, SelectedModel
from src.ai.rag import KnowledgeBase
from src.ai.prompts import get_system_prompt

log = get_logger("ai.engine")

_DEFAULT_TEMP = 0.3
_DEFAULT_TOKENS = 2048


class AIEngine:
    """High-level AI interface that delegates to the appropriate backend.

    Backend selection priority:
    1. ``openrouter`` — if API key is configured and network is available
    2. ``llama`` — local GGUF model via llama-cpp-python
    3. ``none`` — AI disabled (rules-only mode)
    """

    def __init__(self, config: Config):
        self.config = config
        self._llama: LlamaBackend | None = None
        self._openrouter: OpenRouterBackend | None = None
        self._knowledge: KnowledgeBase | None = None
        self._selected_model: SelectedModel | None = None
        self._backend: str = config.ai_backend  # llama | openrouter | none
        self._initialized = False

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------
    def ensure_ready(self) -> None:
        """Load the selected backend (called lazily on first request)."""
        if self._initialized:
            return
        self._initialized = True

        # Knowledge base (always, if available)
        knowledge_dir = self.config.settings.get("paths", {}).get("knowledge_dir")
        if knowledge_dir:
            self._knowledge = KnowledgeBase(knowledge_dir)

        if self._backend == "openrouter":
            self._init_openrouter()
        elif self._backend == "llama":
            self._init_llama()
        else:
            log.info("AI backend: none (disabled)")

    def _init_openrouter(self) -> None:
        api_key = self.config.openrouter_api_key
        if not api_key:
            log.warning("OpenRouter API key not set, falling back to llama")
            self._backend = "llama"
            self._init_llama()
            return

        self._openrouter = OpenRouterBackend(
            api_key=api_key,
            base_url=self.config.openrouter_base_url,
            default_model=self.config.openrouter_model,
            fallback_models=self.config.settings.get("openrouter", {}).get("fallback_models", []),
        )
        log.info("AI backend: OpenRouter (%s)", self.config.openrouter_model)

    def _init_llama(self) -> None:
        models_dir = self.config.settings.get("paths", {}).get("models_dir", "/mnt/usb_data/models")
        self._selected_model = select_model(self.config.models, models_dir)

        if self._selected_model.name == "none" or self._selected_model.file is None:
            log.info("AI backend: none (insufficient resources or no model file)")
            self._backend = "none"
            return

        self._llama = LlamaBackend()
        model_path = Path(models_dir) / self._selected_model.file
        try:
            self._llama.load(
                model_path=model_path,
                context_size=self._selected_model.context_size,
                gpu_layers=self._selected_model.gpu_layers,
            )
            self._backend = "llama"
            log.info("AI backend: llama (%s)", self._selected_model.name)
        except Exception as exc:
            log.error("Failed to load llama model: %s", exc)
            self._backend = "none"
            self._llama = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def backend_name(self) -> str:
        return self._backend

    @property
    def model_name(self) -> str:
        if self._backend == "openrouter":
            return self.config.openrouter_model
        if self._selected_model:
            return self._selected_model.name
        return "none"

    @property
    def is_available(self) -> bool:
        self.ensure_ready()
        return self._backend != "none"

    def _resolve_params(
        self, temperature: float | None, max_tokens: int | None
    ) -> tuple[float, int]:
        """Return temperature and max_tokens, using config defaults only when None."""
        ai_cfg = self.config.settings.get("ai", {})
        temp = temperature if temperature is not None else ai_cfg.get("temperature", _DEFAULT_TEMP)
        tokens = max_tokens if max_tokens is not None else ai_cfg.get("max_tokens", _DEFAULT_TOKENS)
        return float(temp), int(tokens)

    def chat(
        self,
        message: str,
        context: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a response to a user message."""
        self.ensure_ready()

        temp, tokens = self._resolve_params(temperature, max_tokens)
        system_prompt = get_system_prompt(self.config.language)

        prompt = f"{context}\n\n{message}" if context else message
        prompt = self._enrich_with_knowledge(prompt)

        if self._backend == "openrouter" and self._openrouter:
            return self._openrouter.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temp,
                max_tokens=tokens,
            )
        if self._backend == "llama" and self._llama:
            return self._llama.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temp,
                max_tokens=tokens,
            )
        return self._rule_based_response(message)

    def chat_stream(
        self,
        message: str,
        context: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Generator[str, None, None]:
        """Stream a response token by token."""
        self.ensure_ready()

        temp, tokens = self._resolve_params(temperature, max_tokens)
        system_prompt = get_system_prompt(self.config.language)

        prompt = f"{context}\n\n{message}" if context else message
        prompt = self._enrich_with_knowledge(prompt)

        if self._backend == "openrouter" and self._openrouter:
            yield from self._openrouter.generate_stream(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temp,
                max_tokens=tokens,
            )
        elif self._backend == "llama" and self._llama:
            yield from self._llama.generate_stream(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temp,
                max_tokens=tokens,
            )
        else:
            yield self._rule_based_response(message)

    def switch_backend(self, backend: str) -> None:
        """Switch AI backend at runtime."""
        if backend not in ("llama", "openrouter", "none"):
            raise ValueError(f"Unknown backend: {backend}")
        self._backend = backend
        self._initialized = False
        log.info("Backend switched to: %s", backend)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _enrich_with_knowledge(self, prompt: str) -> str:
        """Prepend relevant knowledge base documents to the prompt."""
        if not self._knowledge:
            return prompt

        docs = self._knowledge.search(prompt, top_k=3)
        if not docs:
            return prompt

        context_parts = [
            f"[{doc.get('title', '')}] {doc.get('content', '')}"
            for doc in docs
            if doc.get("title") or doc.get("content")
        ]
        if context_parts:
            return f"Релевантная информация из базы знаний:\n{chr(10).join(context_parts)}\n\n{prompt}"
        return prompt

    @staticmethod
    def _rule_based_response(message: str) -> str:
        """Provide basic responses when AI is unavailable."""
        msg_lower = message.lower()
        if any(w in msg_lower for w in ["диагностик", "скан", "проверк", "scan", "diagnos"]):
            return (
                "AI-модель не загружена. Для запуска диагностики нажмите кнопку "
                "«Полная диагностика» или введите /scan. "
                "Результаты будут показаны без AI-анализа."
            )
        if any(w in msg_lower for w in ["апгрейд", "upgrade", "улучш"]):
            return (
                "AI-модель не загружена. После диагностики (/scan) перейдите на вкладку «Апгрейд». "
                "Для AI-рекомендаций настройте OpenRouter в ⚙️ Настройках."
            )
        return (
            "AI-модель не загружена (недостаточно ресурсов или модель не найдена). "
            "Доступны базовые функции: диагностика (/scan), анализ проблем, рекомендации по апгрейду. "
            "Для AI-анализа: подключитесь к интернету и включите OpenRouter в ⚙️ Настройках, "
            "или запустите на ПК с ≥4 ГБ ОЗУ и скопируйте GGUF-модель в папку models/."
        )
