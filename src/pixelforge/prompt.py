"""Building the generation prompt from the palette, not from prose.

The palette hex list, the canvas aspect and the grid size are read out of the
project's own files. Restating them in a prompt template is how a prompt and a
palette drift apart, and the drift is invisible until somebody lints the output.

A model will not honour a palette exactly -- it does resemblance, not lookup.
Listing the colours still biases it usefully, and the cleaning pipeline is what
makes the result actually compliant.
"""

from __future__ import annotations

from .config import Canvas, Config
from .palette import Palette, to_hex

GRID_RULE = (
    "Render as a pixel grid: every art pixel is a solid {scale}x{scale} block of one "
    "flat colour, aligned to a strict {scale}-pixel grid across the whole image. "
    "Hard edges only. No anti-aliasing, no gradients, no blur, no dithering, no "
    "soft shadows, no texture inside a block."
)

FORM_RULE = (
    "Silhouette first: the subject must be readable as a black shape. Build form "
    "with flat colour areas and a single hard outline one art-pixel wide. Shade to "
    "the form -- brow, cheek, jaw, folds -- never as a left-light/right-dark split."
)

DEFAULT_NEGATIVES = [
    "no text, letters, numbers, signature or watermark",
    "no border, frame, vignette or drop shadow",
    "no photorealism, no painterly brushwork, no 3D render",
    "no perspective grid or ground plane",
    "no multiple characters, no collage, no sprite sheet",
]


def palette_block(palette: Palette, limit: int = 64) -> str:
    entries = [
        "%s %s" % (to_hex(swatch.rgb), swatch.name) if swatch.name.startswith("#") is False
        else to_hex(swatch.rgb)
        for swatch in list(palette)[:limit]
    ]
    return "; ".join(entries)


def build(config: Config, canvas: Canvas, subject: str,
          style: str | None = None, extra_negatives: list[str] | None = None) -> str:
    """The full prompt for one asset."""
    generation = config.generation
    palette = config.palette
    if canvas.sub_palette:
        palette = palette.subset(canvas.sub_palette)

    # Never ask for a colour the cleaner would then hold back. A reserved ramp is
    # dropped unless somewhere this canvas actually lives is allowed to use it.
    blocked = {
        rgb
        for ramp in config.reserved
        if not any(ramp.permits(pattern) for pattern in canvas.paths)
        for rgb in ramp.colors
    }
    if blocked and blocked != palette.colors:
        palette = palette.without(blocked)

    width, height = canvas.frame_size
    scale = max(1, generation.render_scale)
    negatives = DEFAULT_NEGATIVES + list(generation.negatives) + list(extra_negatives or [])

    sections = [
        subject.strip(),
        "",
        GRID_RULE.format(scale=scale),
        "The art is %d by %d art-pixels, so the image is %d by %d pixels overall."
        % (width, height, width * scale, height * scale),
        FORM_RULE,
        "",
        "Use only these colours, and no others: " + palette_block(palette) + ".",
        "Total distinct colours used must be at most %d."
        % (canvas.max_colors or min(16, len(palette))),
        "",
        "Background: a single flat %s filling the entire area behind the subject, "
        "edge to edge, with no shading or texture. The subject must not touch the "
        "image border." % generation.background,
        "The subject is centred, facing the viewer, and fills the frame vertically.",
    ]

    combined_style = " ".join(part for part in (generation.style, style or "") if part).strip()
    if combined_style:
        sections += ["", "Style: " + combined_style]

    sections += ["", "Do not include: " + "; ".join(negatives) + "."]
    return "\n".join(sections)


def describe(config: Config, canvas: Canvas) -> str:
    """One-line summary of what a generation for this canvas will ask for."""
    width, height = canvas.frame_size
    scale = config.generation.render_scale
    return ("%s: %dx%d art-pixels at %dx render (%dx%d px), <= %s colours"
            % (canvas.name, width, height, scale, width * scale, height * scale,
               canvas.max_colors or "palette"))
