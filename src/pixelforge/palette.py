"""Reading and matching fixed palettes.

A palette is an ordered list of named colours. It is read from whatever file the
artist actually keeps -- a GIMP ``.gpl`` loaded in Aseprite, a Lospec hex dump, an
Adobe ``.act``, or a PNG strip -- rather than restated in configuration, because a
restated palette is a second source of truth that can drift from the first.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

RGB = tuple[int, int, int]

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


class PaletteError(Exception):
    """A palette file could not be read, with a message meant for a human."""


@dataclass(frozen=True)
class Swatch:
    name: str
    rgb: RGB

    @property
    def hex(self) -> str:
        return "#%02x%02x%02x" % self.rgb


def _redmean(a: RGB, b: RGB) -> float:
    """Squared perceptual-ish distance. Cheap, and far better than plain RGB.

    Plain Euclidean RGB routinely maps a mid skin tone onto a green of the same
    luminance. This weighting (the "redmean" approximation) costs three extra
    multiplications and stops that.
    """
    mean = (a[0] + b[0]) / 2.0
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return (2 + mean / 256.0) * dr * dr + 4.0 * dg * dg + (2 + (255 - mean) / 256.0) * db * db


def _euclidean(a: RGB, b: RGB) -> float:
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return float(dr * dr + dg * dg + db * db)


METRICS = {"redmean": _redmean, "rgb": _euclidean}


class Palette:
    """An ordered set of colours, with nearest-colour lookup."""

    def __init__(self, swatches: list[Swatch], source: Path | None = None,
                 metric: str = "redmean") -> None:
        if not swatches:
            raise PaletteError("palette is empty")
        if metric not in METRICS:
            raise PaletteError(
                "unknown metric %r; known: %s" % (metric, ", ".join(sorted(METRICS)))
            )
        self.swatches = swatches
        self.source = source
        self.metric = metric
        self._index: dict[RGB, Swatch] = {}
        for swatch in swatches:
            # First declaration wins, so a palette listing a colour twice keeps
            # the more meaningful earlier name rather than the later one.
            self._index.setdefault(swatch.rgb, swatch)
        self._nearest_cache: dict[RGB, Swatch] = {}

    def __len__(self) -> int:
        return len(self.swatches)

    def __contains__(self, rgb: RGB) -> bool:
        return rgb in self._index

    def __iter__(self):
        return iter(self.swatches)

    @property
    def colors(self) -> set[RGB]:
        return set(self._index)

    def name_of(self, rgb: RGB) -> str | None:
        swatch = self._index.get(rgb)
        return swatch.name if swatch else None

    def nearest(self, rgb: RGB) -> Swatch:
        exact = self._index.get(rgb)
        if exact is not None:
            return exact
        cached = self._nearest_cache.get(rgb)
        if cached is not None:
            return cached
        distance = METRICS[self.metric]
        best = min(self.swatches, key=lambda swatch: distance(rgb, swatch.rgb))
        self._nearest_cache[rgb] = best
        return best

    def without(self, colors) -> "Palette":
        """This palette minus some colours, as a snapping target.

        Nearest-colour matching is semantically blind: it will happily map a sail
        highlight onto a ramp reserved for story material, because it is only
        measuring distance. Removing the reserved colours from the candidate set
        is what stops that, and it also picks a better colour -- the next-nearest
        legal one is nearly always the one the artist meant.
        """
        forbidden = set(colors)
        kept = [swatch for swatch in self.swatches if swatch.rgb not in forbidden]
        if not kept:
            raise PaletteError("excluding those colours would empty the palette")
        return Palette(kept, self.source, self.metric)

    def subset(self, names: list[str]) -> "Palette":
        """A palette of the named swatches, for per-context sub-palettes."""
        wanted = {name.lower() for name in names}
        picked = [s for s in self.swatches if s.name.lower() in wanted]
        missing = wanted - {s.name.lower() for s in picked}
        if missing:
            raise PaletteError("no such swatch: %s" % ", ".join(sorted(missing)))
        return Palette(picked, self.source, self.metric)

    # ------------------------------------------------------------------ readers

    @classmethod
    def from_file(cls, path: str | Path, metric: str = "redmean") -> "Palette":
        path = Path(path)
        if not path.exists():
            raise PaletteError("no palette at %s" % path)
        suffix = path.suffix.lower()
        readers = {
            ".gpl": cls._read_gpl,
            ".hex": cls._read_hex,
            ".txt": cls._read_hex,
            ".act": cls._read_act,
            ".png": cls._read_image,
            ".gif": cls._read_image,
            ".bmp": cls._read_image,
        }
        reader = readers.get(suffix)
        if reader is None:
            raise PaletteError(
                "unsupported palette format %r; known: %s"
                % (suffix, ", ".join(sorted(readers)))
            )
        return cls(reader(path), path, metric)

    @staticmethod
    def _read_gpl(path: Path) -> list[Swatch]:
        swatches: list[Swatch] = []
        with io.open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                if line.startswith(("GIMP", "Name:", "Columns:")):
                    continue
                parts = line.split()
                if len(parts) < 3 or not parts[0].isdigit():
                    continue
                rgb = (int(parts[0]), int(parts[1]), int(parts[2]))
                name = " ".join(parts[3:]).strip()
                swatches.append(Swatch(name or Swatch("", rgb).hex, rgb))
        if not swatches:
            raise PaletteError("%s has no colour rows" % path)
        return swatches

    @staticmethod
    def _read_hex(path: Path) -> list[Swatch]:
        """Lospec-style: one #rrggbb (or bare rrggbb) per line, comments allowed."""
        swatches: list[Swatch] = []
        with io.open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                token = line.strip()
                if not token or token.startswith(("#!", "//", ";")):
                    continue
                # A bare '#' comment is ambiguous with a '#rrggbb' colour, so a
                # line is only a comment when it does not parse as a colour.
                match = _HEX.match(token)
                if match is None:
                    if token.startswith("#"):
                        continue
                    raise PaletteError("%s line %d: %r is not a hex colour"
                                       % (path, number, token))
                value = match.group(1)
                rgb = (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
                swatches.append(Swatch("#" + value.lower(), rgb))
        if not swatches:
            raise PaletteError("%s has no colours" % path)
        return swatches

    @staticmethod
    def _read_act(path: Path) -> list[Swatch]:
        """Adobe colour table: 256 RGB triples, optionally followed by a count."""
        blob = path.read_bytes()
        if len(blob) not in (768, 772):
            raise PaletteError("%s is %d bytes; an .act is 768 or 772" % (path, len(blob)))
        count = 256
        if len(blob) == 772:
            count = int.from_bytes(blob[768:770], "big") or 256
        swatches = []
        for index in range(min(count, 256)):
            rgb = (blob[index * 3], blob[index * 3 + 1], blob[index * 3 + 2])
            swatches.append(Swatch("#%02x%02x%02x" % rgb, rgb))
        return swatches

    @staticmethod
    def _read_image(path: Path) -> list[Swatch]:
        """A palette strip: every distinct opaque colour, in scan order."""
        from PIL import Image

        with Image.open(path) as handle:
            image = handle.convert("RGBA")
        seen: dict[RGB, None] = {}
        for pixel in image.getdata():
            if pixel[3] == 0:
                continue
            seen.setdefault(pixel[:3], None)
        if not seen:
            raise PaletteError("%s has no opaque pixels" % path)
        return [Swatch("#%02x%02x%02x" % rgb, rgb) for rgb in seen]

    # ------------------------------------------------------------------ export

    def to_pil_palette_image(self):
        """A mode-'P' image for PIL calls that want a palette source."""
        from PIL import Image

        flat: list[int] = []
        for swatch in self.swatches[:256]:
            flat.extend(swatch.rgb)
        # PIL wants all 256 slots present; pad with the first colour rather than
        # black, so a stray match lands somewhere deliberate.
        pad = self.swatches[0].rgb
        while len(flat) < 768:
            flat.extend(pad)
        image = Image.new("P", (1, 1))
        image.putpalette(flat)
        return image


def parse_hex(value: str) -> RGB:
    """'#rrggbb' or 'rrggbb' -> (r, g, b)."""
    match = _HEX.match(value.strip())
    if match is None:
        raise PaletteError("%r is not a #rrggbb colour" % value)
    digits = match.group(1)
    return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))


def to_hex(rgb: RGB) -> str:
    return "#%02x%02x%02x" % tuple(rgb)
