"""Language-model backends."""

from careercraft.adapters.llm.null import NullProvider
from careercraft.adapters.llm.ollama import OllamaProvider

__all__ = ["NullProvider", "OllamaProvider", "get_provider"]


def get_provider(name: str = "ollama", **kwargs: object) -> object:
    """Resolve a provider by name. Unknown names fall back to the null one."""
    if name == "ollama":
        return OllamaProvider(**kwargs)  # type: ignore[arg-type]
    return NullProvider()
