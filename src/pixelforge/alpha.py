"""Transparency: keying it in, and forcing it to be binary.

Pixel art has no partial alpha. A pixel is there or it is not. Anti-aliased edges
are the single most common thing wrong with art that arrives from a generative
model or from a tool whose layer opacity was not 100%.
"""

from __future__ import annotations

from collections import Counter

from PIL import Image

from ._pixels import read, write
from .palette import RGB


def harden(image: Image.Image, threshold: int = 128) -> Image.Image:
    """Force every alpha value to 0 or 255."""
    rgba = image.convert("RGBA")
    return write(rgba.size, [
        (pixel[0], pixel[1], pixel[2], 255) if pixel[3] >= threshold else (0, 0, 0, 0)
        for pixel in read(rgba)
    ])


def soft_pixels(image: Image.Image) -> int:
    """How many pixels are partially transparent."""
    return sum(1 for pixel in read(image) if 0 < pixel[3] < 255)


def key_color(image: Image.Image, rgb: RGB, tolerance: int = 24) -> Image.Image:
    """Make pixels within ``tolerance`` of ``rgb`` fully transparent.

    Tolerance is a per-channel maximum rather than a distance, so a chroma key
    cannot creep into a colour that merely shares a channel with the key.
    """
    rgba = image.convert("RGBA")
    return write(rgba.size, [
        (0, 0, 0, 0) if _within(pixel, rgb, tolerance) else pixel
        for pixel in read(rgba)
    ])


def _within(pixel, rgb: RGB, tolerance: int) -> bool:
    return (abs(pixel[0] - rgb[0]) <= tolerance
            and abs(pixel[1] - rgb[1]) <= tolerance
            and abs(pixel[2] - rgb[2]) <= tolerance)


def guess_background(image: Image.Image, margin: int = 2) -> RGB | None:
    """The dominant colour around the border, if one clearly dominates.

    Returns None when the border is not overwhelmingly one colour, so a subject
    that touches the frame is never silently eaten. Callers should treat None as
    'ask the human', not as 'no background'.
    """
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width <= margin * 2 or height <= margin * 2:
        return None
    pixels = read(rgba)

    border: Counter = Counter()
    for y in range(height):
        inside_vertical = margin <= y < height - margin
        for x in range(width):
            if inside_vertical and margin <= x < width - margin:
                continue
            pixel = pixels[y * width + x]
            if pixel[3]:
                border[pixel[:3]] += 1

    if not border:
        return None
    (colour, count), = border.most_common(1)
    return colour if count >= sum(border.values()) * 0.9 else None


def autokey(image: Image.Image, tolerance: int = 24,
            threshold: int = 128) -> tuple[Image.Image, RGB | None]:
    """Key out a dominant flat border colour, then harden. Returns what it keyed.

    If the image already has real transparency, only the hardening happens.
    """
    rgba = image.convert("RGBA")
    if any(pixel[3] == 0 for pixel in read(rgba)):
        return harden(rgba, threshold), None
    background = guess_background(rgba)
    if background is None:
        return harden(rgba, threshold), None
    return harden(key_color(rgba, background, tolerance), threshold), background


def connected_regions(image: Image.Image) -> int:
    """Count 4-connected opaque regions.

    Two regions where one was intended means something detached -- a feather off
    a hat, a hand off an arm. It is a one-pixel mistake that is invisible at any
    zoom a human reviews at, and trivial to count.
    """
    rgba = image.convert("RGBA")
    width, height = rgba.size
    opaque = [pixel[3] > 0 for pixel in read(rgba)]
    seen = [False] * len(opaque)
    found = 0
    for start in range(len(opaque)):
        if seen[start] or not opaque[start]:
            continue
        found += 1
        stack = [start]
        seen[start] = True
        while stack:
            index = stack.pop()
            x, y = index % width, index // width
            if x > 0:
                _visit(index - 1, opaque, seen, stack)
            if x < width - 1:
                _visit(index + 1, opaque, seen, stack)
            if y > 0:
                _visit(index - width, opaque, seen, stack)
            if y < height - 1:
                _visit(index + width, opaque, seen, stack)
    return found


def _visit(index: int, opaque: list[bool], seen: list[bool], stack: list[int]) -> None:
    if opaque[index] and not seen[index]:
        seen[index] = True
        stack.append(index)
