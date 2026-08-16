"""The cleaning pipeline, in the order that matters.

    1. key the background and harden alpha   -- at full resolution
    2. snap every colour to the palette      -- at full resolution
    3. mode-downscale to the canvas          -- only now
    4. fit the canvas exactly                -- crop/pad, never resample

Step 2 must come before step 3. Mode filtering only finds a majority once a block
holds a handful of palette colours instead of a few hundred near-identical ones;
run it on raw output and the winner is arbitrary. Step 1 must come before step 2
so a chroma-key background is never snapped into a real palette colour first --
magenta would land on the nearest red and become part of the art.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import alpha as alpha_module
from . import quantize, resample
from .config import Canvas, Config
from .palette import RGB, Palette, to_hex


@dataclass
class CleanResult:
    image: Image.Image
    steps: list[str] = field(default_factory=list)
    remap: list[str] = field(default_factory=list)
    keyed: RGB | None = None

    def summary(self) -> str:
        return "\n".join("  - " + step for step in self.steps)


def clean(image: Image.Image, palette: Palette,
          size: tuple[int, int] | None = None,
          anchor: str = "center",
          key: RGB | None = None,
          tolerance: int = 24,
          threshold: int = 128,
          trim: bool = True,
          explain: bool = True) -> CleanResult:
    """Take an arbitrary image to a palette-locked, hard-alpha, exact-canvas one."""
    result = CleanResult(image.convert("RGBA"))

    # 1. transparency, before anything touches colour
    if key is not None:
        result.image = alpha_module.harden(
            alpha_module.key_color(result.image, key, tolerance), threshold)
        result.keyed = key
        result.steps.append("keyed out %s (tolerance %d) and hardened alpha"
                            % (to_hex(key), tolerance))
    else:
        soft = alpha_module.soft_pixels(result.image)
        result.image, guessed = alpha_module.autokey(result.image, tolerance, threshold)
        result.keyed = guessed
        if guessed:
            result.steps.append("keyed out background %s (detected) and hardened alpha"
                                % to_hex(guessed))
        elif soft:
            result.steps.append("hardened %d partially transparent pixel(s)" % soft)

    # 2. colour, still at full resolution
    counts = quantize.unique_colors(result.image)
    strays = {rgb for rgb in counts if rgb not in palette}
    if strays:
        mapping = quantize.build_mapping(result.image, palette)
        if explain:
            result.remap = quantize.describe_mapping(
                {k: v for k, v in mapping.items() if k != v},
                counts, palette, limit=24)
        result.image = quantize.snap(result.image, palette, mapping)
        result.steps.append("snapped %d of %d colour(s) onto %s"
                            % (len(strays), len(counts),
                               palette.source.name if palette.source else "the palette"))

    # 3. size, only once the colours are countable
    if size is not None:
        if trim:
            trimmed = resample.trim_transparent(result.image)
            if trimmed.size != result.image.size:
                result.steps.append("trimmed transparent margin to %dx%d" % trimmed.size)
                result.image = trimmed
        if result.image.size != tuple(size):
            if result.image.size[0] > size[0] or result.image.size[1] > size[1]:
                # Contain, never cover: the largest reduction that fits the whole
                # subject inside the canvas. Cropping art to fill a canvas loses a
                # hat brim or a boot, and the loss is silent.
                scale = max(result.image.size[0] / size[0], result.image.size[1] / size[1])
                interim = (max(1, min(size[0], round(result.image.size[0] / scale))),
                           max(1, min(size[1], round(result.image.size[1] / scale))))
                result.image = resample.mode_downscale(result.image, interim)
                result.steps.append("mode-downscaled to %dx%d" % interim)
            result.image = resample.fit_canvas(result.image, size, anchor)
            result.steps.append("fitted onto the %dx%d canvas, anchored %s"
                                % (size[0], size[1], anchor))

    return result


def forbidden_colors(config: Config, relative: str) -> set[RGB]:
    """Reserved colours this path may not use, so snapping cannot reach them."""
    blocked: set[RGB] = set()
    for ramp in config.reserved:
        if not ramp.permits(relative):
            blocked.update(ramp.colors)
    return blocked


def clean_for(config: Config, image: Image.Image, canvas: Canvas,
              relative: str | None = None, **overrides) -> CleanResult:
    """``clean`` with the palette, size and anchor taken from a declared canvas.

    ``relative`` is where the result will live, which decides which reserved
    ramps are off-limits. Omit it and every reservation applies -- the safe
    default, since a colour wrongly withheld is a worse match, not a rule broken.
    """
    palette = config.palette
    if canvas.sub_palette:
        palette = palette.subset(canvas.sub_palette)
    blocked = forbidden_colors(config, relative if relative is not None else "")
    if blocked:
        palette = palette.without(blocked)
    options = {"size": canvas.size, "anchor": canvas.anchor}
    options.update(overrides)
    result = clean(image, palette, **options)
    if blocked:
        result.steps.append(
            "held back %d reserved colour(s) this path may not use" % len(blocked))
    return result


def clean_file(config: Config, source: Path, destination: Path,
               canvas: Canvas | None = None, **overrides) -> CleanResult:
    canvas = canvas or config.canvas_for(source)
    with Image.open(source) as handle:
        image = handle.convert("RGBA")
    if canvas is None:
        result = clean(image, config.palette, **overrides)
    else:
        result = clean_for(config, image, canvas, config.relative(destination), **overrides)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result.image.save(destination, "PNG")
    return result
