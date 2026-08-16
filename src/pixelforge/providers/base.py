"""The interface every generation backend implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class GenerationError(Exception):
    """A generation request failed, with a message meant for a human."""


@dataclass
class ProviderResult:
    """Raw bytes as the service returned them. Nothing is cleaned here."""

    images: list[bytes]
    mime_types: list[str] = field(default_factory=list)
    text: str = ""
    model: str = ""

    def __len__(self) -> int:
        return len(self.images)


class Provider:
    """Text (and optionally image) in, image bytes out."""

    #: Set by subclasses. Named so error messages can tell the user what to set.
    api_key_env: str = ""

    def __init__(self, model: str, api_key: str | None = None, timeout: int = 120) -> None:
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def generate(self, prompt: str, reference: Path | None = None,
                 count: int = 1) -> ProviderResult:
        raise NotImplementedError
