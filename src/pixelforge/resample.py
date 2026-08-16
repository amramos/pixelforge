"""Resizing without inventing colours.

Every operation here is closed over the input's colour set: a pixel in the output
was a pixel in the input. No averaging, no interpolation, no new values -- which
is the whole difference between resizing pixel art and resizing a photograph.
"""

from __future__ import annotations

from collections import Counter

from PIL import Image

from ._pixels import read, write

RGBA = tuple[int, int, int, int]
TRANSPARENT: RGBA = (0, 0, 0, 0)


def mode_downscale(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Most common pixel per source block.

    IMPORTANT: run this *after* snapping to the palette, never before. On raw
    generative output almost every pixel in a block is a distinct colour, so
    there is no majority to find and the winner is arbitrary -- no better than
    NEAREST. Once the image holds only palette colours, blocks have real
    majorities and this preserves flat regions and hard edges exactly.
    """
    width, height = size
    if width < 1 or height < 1:
        raise ValueError("target size must be positive, got %r" % (size,))
    rgba = image.convert("RGBA")
    source_w, source_h = rgba.size
    pixels = read(rgba)

    out: list[RGBA] = []
    for y in range(height):
        top = y * source_h // height
        bottom = max(top + 1, (y + 1) * source_h // height)
        for x in range(width):
            left = x * source_w // width
            right = max(left + 1, (x + 1) * source_w // width)
            counts: Counter = Counter()
            for row in range(top, bottom):
                offset = row * source_w
                for column in range(left, right):
                    pixel = pixels[offset + column]
                    counts[TRANSPARENT if pixel[3] == 0 else pixel] += 1
            # Ties break toward the more opaque, then the darker colour, so the
            # result is deterministic across runs and platforms.
            best = max(counts.items(), key=lambda item: (item[1], item[0][3], -sum(item[0][:3])))
            out.append(best[0])

    return write(size, out)


def integer_upscale(image: Image.Image, factor: int) -> Image.Image:
    """Nearest-neighbour scale by a whole number. Any other factor is a bug."""
    if factor < 1:
        raise ValueError("upscale factor must be >= 1, got %d" % factor)
    width, height = image.size
    return image.resize((width * factor, height * factor), Image.Resampling.NEAREST)


def detect_integer_upscale(image: Image.Image, maximum: int = 32) -> int | None:
    """Largest N for which the image is an exact N-times pixel-doubling.

    Catches art that was saved at 4x by mistake: it looks correct and is four
    times too big, and every downstream size check reads as a mismatch.
    """
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = read(rgba)
    best = None
    for factor in range(2, maximum + 1):
        if width % factor or height % factor:
            continue
        if _is_blocked(pixels, width, height, factor):
            best = factor
    return best


def _is_blocked(pixels: list[RGBA], width: int, height: int, factor: int) -> bool:
    for y in range(0, height, factor):
        for x in range(0, width, factor):
            first = pixels[y * width + x]
            for row in range(y, y + factor):
                offset = row * width
                for column in range(x, x + factor):
                    if pixels[offset + column] != first:
                        return False
    return True


def fit_canvas(image: Image.Image, size: tuple[int, int],
               anchor: str = "center") -> Image.Image:
    """Crop and/or pad onto an exact canvas. Never resamples.

    ``anchor`` is one of center, top, bottom, left, right, or a corner pair such
    as 'bottom-left' -- for sprites that must sit on a baseline rather than float.
    """
    rgba = image.convert("RGBA")
    target_w, target_h = size
    source_w, source_h = rgba.size
    horizontal, vertical = _anchor_parts(anchor)

    left = {"left": 0, "center": (target_w - source_w) // 2,
            "right": target_w - source_w}[horizontal]
    top = {"top": 0, "center": (target_h - source_h) // 2,
           "bottom": target_h - source_h}[vertical]

    canvas = Image.new("RGBA", size, TRANSPARENT)
    canvas.alpha_composite(rgba, dest=(max(left, 0), max(top, 0)),
                           source=(max(-left, 0), max(-top, 0)))
    return canvas


def _anchor_parts(anchor: str) -> tuple[str, str]:
    horizontal, vertical = "center", "center"
    for token in anchor.lower().replace("_", "-").split("-"):
        if token in ("left", "right"):
            horizontal = token
        elif token in ("top", "bottom"):
            vertical = token
        elif token != "center":
            raise ValueError("unknown anchor %r" % anchor)
    return horizontal, vertical


def trim_transparent(image: Image.Image) -> Image.Image:
    """Drop fully transparent margins. Returns the image unchanged if empty."""
    rgba = image.convert("RGBA")
    box = rgba.getbbox()
    return rgba if box is None else rgba.crop(box)


def content_size(image: Image.Image) -> tuple[int, int]:
    """Size of the opaque content, ignoring transparent margins."""
    box = image.convert("RGBA").getbbox()
    return (0, 0) if box is None else (box[2] - box[0], box[3] - box[1])
