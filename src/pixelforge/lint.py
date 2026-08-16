"""Rules an asset has to pass.

Each rule is a small function over one file. They report rather than fix: a rule
that quietly rewrote somebody's art would be worse than one that failed loudly.

Severity is two-valued on purpose. ``error`` means the asset is wrong. ``warn``
means it is unfinished, which is a normal state on a project where the art is
being drawn in parallel with the code -- missing art must never be an error.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from . import alpha as alpha_module
from . import quantize, resample
from .config import Canvas, Config
from .palette import to_hex

ERROR = "error"
WARN = "warn"


@dataclass
class Finding:
    path: str
    rule: str
    severity: str
    message: str

    def format(self) -> str:
        mark = "ERROR" if self.severity == ERROR else "warn "
        return "%s  %-16s %s\n         %s" % (mark, self.rule, self.path, self.message)


@dataclass
class Report:
    findings: list[Finding]
    checked: int

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARN]

    @property
    def ok(self) -> bool:
        return not self.errors


def lint(config: Config, canvas: Canvas | None = None,
         paths: list[Path] | None = None) -> Report:
    targets = paths if paths is not None else config.files(canvas)
    manifest = _load_manifest(config)
    findings: list[Finding] = []
    checked = 0
    for path in targets:
        profile = canvas or config.canvas_for(path)
        findings.extend(lint_file(path, config, profile, manifest))
        checked += 1
    return Report(findings, checked)


def lint_file(path: Path, config: Config, canvas: Canvas | None,
              manifest: set[str] | None = None) -> list[Finding]:
    relative = config.relative(path)
    findings: list[Finding] = []

    def add(rule: str, severity: str, message: str) -> None:
        findings.append(Finding(relative, rule, severity, message))

    try:
        with Image.open(path) as handle:
            image = handle.convert("RGBA")
    except (UnidentifiedImageError, OSError) as failure:
        add("unreadable", ERROR, str(failure))
        return findings

    if config.naming_pattern and not config.exempt_from_naming(relative):
        if not re.match(config.naming_pattern, path.name):
            add("naming", ERROR, "%r does not match %s" % (path.name, config.naming_pattern))

    palette = config.palette
    if canvas and canvas.sub_palette:
        palette = palette.subset(canvas.sub_palette)

    strays = quantize.off_palette(image, palette)
    if strays:
        examples = ", ".join(
            "%s x%d -> %s" % (to_hex(rgb), count, to_hex(palette.nearest(rgb).rgb))
            for rgb, count in strays.most_common(4)
        )
        add("off-palette", ERROR,
            "%d colour(s) outside %s: %s%s"
            % (len(strays), _palette_label(config, canvas), examples,
               ", ..." if len(strays) > 4 else ""))

    for ramp in config.reserved:
        used = [rgb for rgb in ramp.colors if rgb in quantize.unique_colors(image)]
        if used and not ramp.permits(relative):
            add("reserved", ERROR,
                "uses reserved %s colour(s) %s, which this path may not"
                % (ramp.name, ", ".join(to_hex(rgb) for rgb in used)))

    soft = alpha_module.soft_pixels(image)
    if soft and (canvas is None or canvas.hard_alpha):
        add("soft-alpha", ERROR,
            "%d pixel(s) are partially transparent; pixel art alpha is 0 or 255" % soft)

    if canvas is None:
        add("unclaimed", WARN, "no [[canvas]] in pixelforge.toml matches this path")
        return findings

    if image.size != tuple(canvas.size):
        factor = resample.detect_integer_upscale(image)
        hint = ""
        if factor:
            scaled = (image.size[0] // factor, image.size[1] // factor)
            hint = " -- it is an exact %dx pixel-doubling of %dx%d" % (factor, *scaled)
        add("canvas-size", ERROR,
            "is %dx%d, canvas %r is %dx%d%s"
            % (*image.size, canvas.name, *canvas.size, hint))

    if canvas.max_colors is not None:
        used = len(quantize.unique_colors(image))
        if used > canvas.max_colors:
            add("colour-budget", ERROR,
                "%d colours, canvas %r allows %d" % (used, canvas.name, canvas.max_colors))

    if canvas.single_region:
        regions = alpha_module.connected_regions(image)
        if regions > 1:
            add("regions", ERROR,
                "%d separate opaque regions; canvas %r expects one connected shape"
                % (regions, canvas.name))

    if not image.getbbox():
        add("empty", WARN, "has no opaque pixels")

    if manifest is not None and relative not in manifest:
        add("provenance", WARN, "no row in %s" % config.provenance.manifest)

    return findings


def _palette_label(config: Config, canvas: Canvas | None) -> str:
    if canvas and canvas.sub_palette:
        return "canvas %r's sub-palette" % canvas.name
    source = config.palette.source
    return source.name if source else "the palette"


def _load_manifest(config: Config) -> set[str] | None:
    if not config.provenance.manifest:
        return None
    path = config.root / config.provenance.manifest
    if not path.exists():
        return None
    rows: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            value = row.get(config.provenance.path_column)
            if value:
                rows.add(value.strip().replace("\\", "/"))
    return rows
