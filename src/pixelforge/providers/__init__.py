"""Image generation backends.

One adapter per service, behind a two-method interface, so swapping the model is
a config change rather than a rewrite of the pipeline that consumes it.
"""

from __future__ import annotations

from .base import GenerationError, Provider, ProviderResult

_REGISTRY: dict[str, type[Provider]] = {}


def register(name: str, provider: type[Provider]) -> None:
    _REGISTRY[name] = provider


def get(name: str) -> type[Provider]:
    if name not in _REGISTRY:
        raise GenerationError(
            "unknown provider %r; available: %s" % (name, ", ".join(sorted(_REGISTRY)))
        )
    return _REGISTRY[name]


def available() -> list[str]:
    return sorted(_REGISTRY)


from .gemini import Gemini  # noqa: E402  (registers itself)

register("gemini", Gemini)

__all__ = ["Provider", "ProviderResult", "GenerationError", "get", "register", "available"]
