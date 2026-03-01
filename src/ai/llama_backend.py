"""Local AI inference backend using llama-cpp-python."""

from pathlib import Path
from typing import Generator

from src.core.logger import get_logger

log = get_logger("ai.llama")


class LlamaBackend:
    """Wrapper around llama-cpp-python for local GGUF model inference."""

    def __init__(self):
        self._model = None
        self._model_path: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(
        self,
        model_path: str | Path,
        context_size: int = 4096,
        gpu_layers: int = 0,
    ) -> None:
        """Load a GGUF model into memory."""
        model_path = str(model_path)
        if self._model_path == model_path and self._model is not None:
            log.debug("Model already loaded: %s", model_path)
            return

        log.info("Loading model: %s (ctx=%d, gpu_layers=%d)", model_path, context_size, gpu_layers)
        try:
            from llama_cpp import Llama

            self._model = Llama(
                model_path=model_path,
                n_ctx=context_size,
                n_gpu_layers=gpu_layers,
                use_mmap=True,
                verbose=False,
            )
            self._model_path = model_path
            log.info("Model loaded successfully")
        except Exception as exc:
            log.error("Failed to load model: %s", exc)
            self._model = None
            raise

    def unload(self) -> None:
        """Free the model from memory."""
        if self._model is not None:
            del self._model
            self._model = None
            self._model_path = None
            log.info("Model unloaded")

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
        stop: list[str] | None = None,
    ) -> str:
        """Generate a completion for the given prompt."""
        if self._model is None:
            raise RuntimeError("No model loaded")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._model.create_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop or [],
            )
            content = response["choices"][0]["message"]["content"]
            return content.strip()
        except Exception as exc:
            log.error("Generation failed: %s", exc)
            raise

    def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> Generator[str, None, None]:
        """Stream tokens as they are generated."""
        if self._model is None:
            raise RuntimeError("No model loaded")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            stream = self._model.create_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                delta = chunk["choices"][0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    yield token
        except Exception as exc:
            log.error("Streaming generation failed: %s", exc)
            raise
