"""pixelforge -- palette-locked pixel art tooling.

Lint, clean, preview and generate pixel art against a fixed palette and fixed
canvases. Everything project-specific lives in a ``pixelforge.toml``; nothing in
this package knows about any particular game.
"""

__version__ = "0.1.0"

from .config import Config, ConfigError  # noqa: F401
from .palette import Palette, PaletteError, Swatch  # noqa: F401

__all__ = ["Config", "ConfigError", "Palette", "PaletteError", "Swatch", "__version__"]
