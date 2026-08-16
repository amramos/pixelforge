"""Snapping an image onto a fixed palette.

Deliberately not ``Image.quantize(colors=N)``. That picks the N colours that best
represent *this image* -- an adaptive palette, which is the opposite of the job
here. It also dithers by default, spraying Floyd-Steinberg checkerboard across
flat regions, which is precisely what pixel art is not.
"""

from __future__ import annotations

from collections import Counter

from PIL import Image

from ._pixels import read, write
from .palette import RGB, Palette, to_hex


def unique_colors(image: Image.Image, include_transparent: bool = False) -> Counter:
    """Opaque colour -> pixel count."""
    counts: Counter = Counter()
    for pixel in read(image):
        if pixel[3] == 0 and not include_transparent:
            continue
        counts[pixel[:3]] += 1
    return counts


def off_palette(image: Image.Image, palette: Palette) -> Counter:
    """The opaque colours that are not in the palette, by pixel count."""
    return Counter({rgb: count for rgb, count in unique_colors(image).items()
                    if rgb not in palette})


def build_mapping(image: Image.Image, palette: Palette) -> dict[RGB, RGB]:
    """Every distinct colour in the image -> its palette target.

    Built over distinct colours rather than pixels, so a 1024x1024 render with a
    few thousand colours costs a few thousand lookups instead of a million.
    """
    return {rgb: palette.nearest(rgb).rgb for rgb in unique_colors(image)}


def snap(image: Image.Image, palette: Palette,
         mapping: dict[RGB, RGB] | None = None) -> Image.Image:
    """Every opaque pixel moved to its nearest palette colour. Alpha untouched.

    Alpha survives because the remap is done by hand rather than through PIL's
    palette mode, which is 8-bit indexed and would flatten it.
    """
    rgba = image.convert("RGBA")
    if mapping is None:
        mapping = build_mapping(rgba, palette)
    return write(rgba.size, [
        (*mapping.get(pixel[:3], pixel[:3]), pixel[3]) if pixel[3] else (0, 0, 0, 0)
        for pixel in read(rgba)
    ])


def describe_mapping(mapping: dict[RGB, RGB], counts: Counter, palette: Palette,
                     limit: int = 0) -> list[str]:
    """Human-readable remap table, busiest colour first.

    Printed before writing anything, because a silent colour change to somebody's
    art is worse than a refusal.
    """
    rows = sorted(mapping.items(), key=lambda item: -counts.get(item[0], 0))
    if limit:
        rows = rows[:limit]
    lines = []
    for source, target in rows:
        if source == target:
            lines.append("  %s %8d px  already in palette (%s)"
                         % (to_hex(source), counts.get(source, 0), palette.name_of(source)))
        else:
            lines.append("  %s %8d px  ->  %s  %s"
                         % (to_hex(source), counts.get(source, 0), to_hex(target),
                            palette.name_of(target) or ""))
    return lines
