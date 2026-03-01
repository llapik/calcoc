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

    def chat(
        self,
        message: str,
        context: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a response to a user message."""
        self.ensure_ready()

        temp = temperature or self.config.settings.get("ai", {}).get("temperature", 0.3)
        tokens = max_tokens or self.config.settings.get("ai", {}).get("max_tokens", 2048)
        system_prompt = get_system_prompt(self.config.language)

        # Enrich with RAG context
        prompt = message
        if context:
            prompt = f"{context}\n\n{message}"
        prompt = self._enrich_with_knowledge(prompt)

        if self._backend == "openrouter" and self._openrouter:
            return self._openrouter.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temp,
                max_tokens=tokens,
            )
        elif self._backend == "llama" and self._llama:
            return self._llama.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temp,
                max_tokens=tokens,
            )
        else:
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

        temp = temperature or self.config.settings.get("ai", {}).get("temperature", 0.3)
        tokens = max_tokens or self.config.settings.get("ai", {}).get("max_tokens", 2048)
        system_prompt = get_system_prompt(self.config.language)

        prompt = message
        if context:
            prompt = f"{context}\n\n{message}"
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
        """Add relevant knowledge base documents to the prompt."""
        if not self._knowledge:
            return prompt

        docs = self._knowledge.search(prompt, top_k=3)
        if not docs:
            return prompt

        context_parts = []
        for doc in docs:
            title = doc.get("title", "")
            content = doc.get("content", "")
            if title or content:
                context_parts.append(f"[{title}] {content}")

        if context_parts:
            knowledge_text = "\n".join(context_parts)
            return f"Релевантная информация из базы знаний:\n{knowledge_text}\n\n{prompt}"
        return prompt

    @staticmethod
    def _rule_based_response(message: str) -> str:
        """Provide basic responses when AI is unavailable."""
        msg_lower = message.lower()
        if any(w in msg_lower for w in ["диагностик", "скан", "проверк", "scan", "diagnos"]):
            return (
                "AI-модель не загружена. Для запуска диагностики используйте команду /scan. "
                "Результаты будут показаны в виде таблицы без AI-анализа."
            )
        if any(w in msg_lower for w in ["апгрейд", "upgrade", "улучш"]):
            return (
                "AI-модель не загружена. Информация о системе доступна через /scan. "
                "Для получения рекомендаций по апгрейду подключитесь к интернету и "
                "включите OpenRouter в настройках."
            )
        return (
            "AI-модель не загружена из-за ограниченных ресурсов. "
            "Доступны только базовые функции: диагностика (/scan), "
            "исправление проблем (/fix), проверка на вирусы (/malware_scan). "
            "Для AI-анализа настройте OpenRouter или запустите на ПК с ≥4 ГБ ОЗУ."
        )
