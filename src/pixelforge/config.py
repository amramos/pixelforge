"""``pixelforge.toml`` -- everything project-specific lives here.

Nothing in this package knows about any particular game. A project declares its
palette, its canvases and its rules; the engine reads them. That is the whole
line between "a tool" and "a tool for one repository".
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .palette import Palette, PaletteError, RGB, parse_hex

CONFIG_NAME = "pixelforge.toml"


class ConfigError(Exception):
    """A configuration problem, with a message meant for a human."""


@dataclass
class Reserved:
    """A ramp that may only appear in some places (danger reds, story colours)."""

    name: str
    colors: list[RGB]
    allow_in: list[str] = field(default_factory=list)

    def permits(self, relative: str) -> bool:
        return any(fnmatch.fnmatch(relative, pattern) for pattern in self.allow_in)


@dataclass
class Canvas:
    """One class of asset: its exact size, where it lives, what it may contain."""

    name: str
    size: tuple[int, int]
    paths: list[str]
    exclude: list[str] = field(default_factory=list)
    frames: int = 1
    max_colors: int | None = None
    hard_alpha: bool = True
    single_region: bool = False
    anchor: str = "center"
    sub_palette: list[str] = field(default_factory=list)

    @property
    def frame_size(self) -> tuple[int, int]:
        if self.frames <= 1:
            return self.size
        width, height = self.size
        if width % self.frames:
            raise ConfigError(
                "canvas %r is %d wide and declares %d frames, which does not divide"
                % (self.name, width, self.frames)
            )
        return (width // self.frames, height)

    def matches(self, relative: str) -> bool:
        if any(fnmatch.fnmatch(relative, pattern) for pattern in self.exclude):
            return False
        return any(fnmatch.fnmatch(relative, pattern) for pattern in self.paths)


@dataclass
class Generation:
    provider: str = "gemini"
    model: str = "gemini-3-pro-image"
    staging: str = ".pixelforge/staging"
    render_scale: int = 16
    background: str = "#ff00ff"
    style: str = ""
    negatives: list[str] = field(default_factory=list)


@dataclass
class Provenance:
    manifest: str | None = None
    path_column: str = "path"
    origin_column: str = "origin"
    ai_origin_value: str = "ai-generated"


@dataclass
class Config:
    root: Path
    palette: Palette
    canvases: list[Canvas]
    reserved: list[Reserved] = field(default_factory=list)
    naming_pattern: str | None = None
    naming_exempt: list[str] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    generation: Generation = field(default_factory=Generation)

    def canvas_for(self, path: Path) -> Canvas | None:
        relative = self.relative(path)
        for canvas in self.canvases:
            if canvas.matches(relative):
                return canvas
        return None

    def canvas_named(self, name: str) -> Canvas:
        for canvas in self.canvases:
            if canvas.name == name:
                return canvas
        raise ConfigError(
            "no canvas named %r; declared: %s"
            % (name, ", ".join(c.name for c in self.canvases) or "(none)")
        )

    def relative(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return Path(path).as_posix()

    def exempt_from_naming(self, relative: str) -> bool:
        return any(fnmatch.fnmatch(relative, pattern) for pattern in self.naming_exempt)

    def files(self, canvas: Canvas | None = None) -> list[Path]:
        """Every file matched by the given canvas, or by any of them."""
        wanted = [canvas] if canvas else self.canvases
        found: dict[str, Path] = {}
        for entry in wanted:
            for pattern in entry.paths:
                for path in sorted(self.root.glob(pattern)):
                    if path.is_file() and entry.matches(self.relative(path)):
                        found[str(path)] = path
        return list(found.values())

    # ------------------------------------------------------------------ loading

    @classmethod
    def find(cls, start: Path | None = None) -> Path:
        """Nearest ``pixelforge.toml`` at or above ``start``."""
        current = (start or Path.cwd()).resolve()
        for directory in [current, *current.parents]:
            candidate = directory / CONFIG_NAME
            if candidate.exists():
                return candidate
        raise ConfigError(
            "no %s found in %s or any parent -- run 'pixelforge init'" % (CONFIG_NAME, current)
        )

    @classmethod
    def load(cls, path: Path | None = None, start: Path | None = None) -> "Config":
        config_path = Path(path) if path else cls.find(start)
        try:
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as failure:
            raise ConfigError("%s: %s" % (config_path, failure)) from failure
        root = config_path.parent.resolve()
        return cls._from_data(data, root, config_path)

    @classmethod
    def _from_data(cls, data: dict, root: Path, where: Path) -> "Config":
        palette_table = data.get("palette")
        if not isinstance(palette_table, dict) or "source" not in palette_table:
            raise ConfigError("%s: [palette] needs a 'source' pointing at a palette file"
                              % where)
        palette_path = root / str(palette_table["source"])
        try:
            palette = Palette.from_file(palette_path,
                                        str(palette_table.get("metric", "redmean")))
        except PaletteError as failure:
            raise ConfigError("%s: %s" % (where, failure)) from failure

        reserved = [
            Reserved(
                name=str(entry.get("name", "reserved")),
                colors=[parse_hex(value) for value in entry.get("colors", [])],
                allow_in=[str(value) for value in entry.get("allow_in", [])],
            )
            for entry in palette_table.get("reserved", [])
        ]

        canvases = [cls._canvas(entry, where) for entry in data.get("canvas", [])]
        if not canvases:
            raise ConfigError("%s: declare at least one [[canvas]]" % where)
        names = [canvas.name for canvas in canvases]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ConfigError("%s: canvas name used twice: %s"
                              % (where, ", ".join(sorted(duplicates))))

        naming = data.get("naming", {})
        pattern = naming.get("pattern")
        if pattern:
            try:
                re.compile(str(pattern))
            except re.error as failure:
                raise ConfigError("%s: [naming] pattern is not a regex: %s"
                                  % (where, failure)) from failure

        provenance_table = data.get("provenance", {})
        generate_table = data.get("generate", {})

        return cls(
            root=root,
            palette=palette,
            canvases=canvases,
            reserved=reserved,
            naming_pattern=str(pattern) if pattern else None,
            naming_exempt=[str(value) for value in naming.get("exempt", [])],
            provenance=Provenance(
                manifest=(str(provenance_table["manifest"])
                          if "manifest" in provenance_table else None),
                path_column=str(provenance_table.get("path_column", "path")),
                origin_column=str(provenance_table.get("origin_column", "origin")),
                ai_origin_value=str(provenance_table.get("ai_origin_value", "ai-generated")),
            ),
            generation=Generation(
                provider=str(generate_table.get("provider", "gemini")),
                model=str(generate_table.get("model", "gemini-3-pro-image")),
                staging=str(generate_table.get("staging", ".pixelforge/staging")),
                render_scale=int(generate_table.get("render_scale", 16)),
                background=str(generate_table.get("background", "#ff00ff")),
                style=str(generate_table.get("style", "")),
                negatives=[str(value) for value in generate_table.get("negatives", [])],
            ),
        )

    @staticmethod
    def _canvas(entry: dict, where: Path) -> Canvas:
        name = str(entry.get("name", "")) or "(unnamed)"
        size = entry.get("size")
        if not (isinstance(size, list) and len(size) == 2):
            raise ConfigError("%s: canvas %r needs size = [width, height]" % (where, name))
        paths = entry.get("paths", [])
        if not paths:
            raise ConfigError("%s: canvas %r needs at least one path glob" % (where, name))
        return Canvas(
            name=name,
            size=(int(size[0]), int(size[1])),
            paths=[str(value) for value in paths],
            exclude=[str(value) for value in entry.get("exclude", [])],
            frames=int(entry.get("frames", 1)),
            max_colors=(int(entry["max_colors"]) if "max_colors" in entry else None),
            hard_alpha=bool(entry.get("hard_alpha", True)),
            single_region=bool(entry.get("single_region", False)),
            anchor=str(entry.get("anchor", "center")),
            sub_palette=[str(value) for value in entry.get("sub_palette", [])],
        )
