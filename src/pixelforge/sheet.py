"""Looking at the work: silhouettes, contact sheets, before-and-afters.

The silhouette render exists because silhouette is the property most pixel art
style guides make load-bearing, and it is the one a colour render hides. Missing
arms are invisible in colour and obvious in black.
"""

from __future__ import annotations

from PIL import Image

from ._pixels import read, write
from .palette import RGB
from .resample import integer_upscale

RGBA = tuple[int, int, int, int]


def silhouette(image: Image.Image, ink: RGB = (26, 20, 32),
               ground: RGB = (220, 216, 188)) -> Image.Image:
    """Opaque pixels flat black, everything else flat paper."""
    rgba = image.convert("RGBA")
    solid = (*ink, 255)
    empty = (*ground, 255)
    return write(rgba.size, [solid if pixel[3] else empty for pixel in read(rgba)])


def on_background(image: Image.Image, color: RGB) -> Image.Image:
    """Composite over a flat colour, so transparent art is visible at all."""
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (*color, 255))
    canvas.alpha_composite(rgba)
    return canvas


def contact_sheet(images: list[Image.Image], columns: int = 0, scale: int = 1,
                  gap: int = 8, background: RGB = (26, 20, 32),
                  pad: int = 8) -> Image.Image:
    """Tile images on a grid at an integer scale. Cells are the largest image."""
    if not images:
        raise ValueError("nothing to tile")
    scaled = [integer_upscale(image.convert("RGBA"), scale) for image in images]
    cell_w = max(image.width for image in scaled)
    cell_h = max(image.height for image in scaled)
    columns = columns or min(len(scaled), max(1, int(len(scaled) ** 0.5 + 0.5)))
    rows = (len(scaled) + columns - 1) // columns

    width = pad * 2 + columns * cell_w + (columns - 1) * gap
    height = pad * 2 + rows * cell_h + (rows - 1) * gap
    sheet = Image.new("RGBA", (width, height), (*background, 255))

    for index, image in enumerate(scaled):
        column, row = index % columns, index // columns
        left = pad + column * (cell_w + gap) + (cell_w - image.width) // 2
        top = pad + row * (cell_h + gap) + (cell_h - image.height) // 2
        sheet.alpha_composite(image, dest=(left, top))
    return sheet


def review(image: Image.Image, scale: int = 8,
           ground: RGB = (45, 85, 102)) -> Image.Image:
    """The render most worth looking at: colour beside silhouette."""
    return contact_sheet(
        [on_background(image, ground), silhouette(image)],
        columns=2, scale=scale, gap=scale * 2, background=ground,
    )


def _to_height(image: Image.Image, target: int) -> Image.Image:
    """Scale for display only: integer NEAREST up, LANCZOS down.

    Downscaling for a preview is the one place this package resamples, because
    the alternative is a 1024px source next to a 48px result. It never touches a
    file that gets written as an asset.
    """
    if image.height == 0:
        return image
    if image.height <= target:
        return integer_upscale(image, max(1, target // image.height))
    width = max(1, round(image.width * target / image.height))
    return image.resize((width, target), Image.Resampling.LANCZOS)


def before_after(before: Image.Image, after: Image.Image, height: int = 384,
                 ground: RGB = (45, 85, 102)) -> Image.Image:
    """Source and result side by side, both brought to the same display height."""
    pair = [_to_height(on_background(image.convert("RGBA"), ground), height)
            for image in (before, after)]
    return contact_sheet(pair, columns=2, scale=1, gap=16, background=ground)
