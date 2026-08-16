"""Reading and writing pixel buffers.

Via ``tobytes``/``frombytes`` rather than ``getdata``/``putdata``: those two are
deprecated for removal in Pillow 14, and the byte path is several times faster
besides. Everything in this package goes through here, so the choice is made in
exactly one place.
"""

from __future__ import annotations

import struct
from itertools import chain

from PIL import Image

RGBA = tuple[int, int, int, int]

_UNPACK = struct.Struct("4B").iter_unpack


def read(image: Image.Image) -> list[RGBA]:
    """Every pixel as an (r, g, b, a) tuple, row-major."""
    return list(_UNPACK(image.convert("RGBA").tobytes()))


def write(size: tuple[int, int], pixels) -> Image.Image:
    """An RGBA image from a sequence of (r, g, b, a) tuples."""
    return Image.frombytes("RGBA", size, bytes(chain.from_iterable(pixels)))
