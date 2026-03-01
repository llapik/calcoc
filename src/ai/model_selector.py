"""Dynamic AI model selection based on available system resources."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.core.logger import get_logger

log = get_logger("ai.model_selector")


@dataclass
class SelectedModel:
    name: str
    file: str | None
    context_size: int
    gpu_layers: int
    description: str


def get_available_ram_mb() -> int:
    """Return total available RAM in MB (using /proc/meminfo)."""
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass

    # Fallback to psutil
    try:
        import psutil
        return int(psutil.virtual_memory().total / (1024 * 1024))
    except ImportError:
        return 0


def has_gpu_support() -> bool:
    """Check if GPU acceleration is available for llama.cpp."""
    import subprocess
    # Check for NVIDIA GPU with CUDA
    try:
        subprocess.check_output(["nvidia-smi"], stderr=subprocess.DEVNULL, timeout=5)
        return True
    except Exception:
        pass
    # Check for ROCm (AMD)
    try:
        subprocess.check_output(["rocm-smi"], stderr=subprocess.DEVNULL, timeout=5)
        return True
    except Exception:
        pass
    return False


def select_model(models_config: dict, models_dir: str | Path) -> SelectedModel:
    """Select the best AI model for the current hardware.

    Returns the highest-tier model whose RAM requirements are met and
    whose GGUF file exists on disk.
    """
    ram_mb = get_available_ram_mb()
    reserve = models_config.get("selection", {}).get("memory_reserve_mb", 512)
    effective_ram = ram_mb - reserve
    gpu = has_gpu_support() and models_config.get("selection", {}).get("prefer_gpu", True)

    models_dir = Path(models_dir)
    candidates = models_config.get("models", [])

    log.info("System RAM: %d MB (effective: %d MB), GPU: %s", ram_mb, effective_ram, gpu)

    # Sort by min_ram descending to pick the best model first
    candidates_sorted = sorted(candidates, key=lambda m: m.get("min_ram_mb", 0), reverse=True)

    for model in candidates_sorted:
        min_ram = model.get("min_ram_mb", 0)
        max_ram = model.get("max_ram_mb", 999999)

        if effective_ram < min_ram:
            continue
        if effective_ram > max_ram:
            continue

        model_file = model.get("file")
        if model_file and not (models_dir / model_file).exists():
            log.debug("Model file not found: %s", models_dir / model_file)
            continue

        gpu_layers = model.get("gpu_layers", 0) if gpu else 0

        selected = SelectedModel(
            name=model["name"],
            file=model_file,
            context_size=model.get("context_size", 2048),
            gpu_layers=gpu_layers,
            description=model.get("description", ""),
        )
        log.info("Selected model: %s (%s)", selected.name, selected.description)
        return selected

    # Fallback: no AI
    log.warning("No suitable model found, AI will be disabled")
    return SelectedModel(
        name="none",
        file=None,
        context_size=0,
        gpu_layers=0,
        description="AI отключён",
    )
