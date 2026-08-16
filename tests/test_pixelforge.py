"""Tests. Standard library only -- ``python -m unittest discover tests``.

The invariants worth protecting are the ones that are easy to break silently:
that nothing invents a colour, that alpha stays binary, and above all that
cleaning quantizes *before* it downscales.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from PIL import Image

from pixelforge import clean as clean_module
from pixelforge import alpha, lint, prompt, quantize, resample
from pixelforge._pixels import read
from pixelforge.config import Config, ConfigError
from pixelforge.palette import Palette, PaletteError, parse_hex, to_hex

RED = (200, 40, 40)
GREEN = (40, 200, 40)
BLUE = (40, 40, 200)

GPL = """GIMP Palette
Name: Test
Columns: 4
#
200  40  40\tRed
 40 200  40\tGreen
 40  40 200\tBlue
255 255 255\tWhite
  0   0   0\tBlack
"""


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def solid(size, color) -> Image.Image:
    return Image.new("RGBA", size, (*color, 255))


def patterned(size=(3, 3)) -> Image.Image:
    """Neighbouring pixels always differ, so an upscale factor is unambiguous.

    A solid image is an exact N-times doubling for every N that divides it, which
    is true and useless -- upscale detection can only mean anything on art that
    actually varies.
    """
    palette = [RED, GREEN, BLUE, (255, 255, 255), (0, 0, 0)]
    image = Image.new("RGBA", size)
    image.putdata([(*palette[index % len(palette)], 255)
                   for index in range(size[0] * size[1])])
    return image


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)
        self.palette_path = write(self.root, "palette.gpl", GPL)
        self.palette = Palette.from_file(self.palette_path)


class TestPalette(TempCase):
    def test_reads_gpl_in_order_with_names(self):
        self.assertEqual(len(self.palette), 5)
        self.assertEqual(self.palette.swatches[0].name, "Red")
        self.assertEqual(self.palette.swatches[0].rgb, RED)

    def test_membership_and_naming(self):
        self.assertIn(RED, self.palette)
        self.assertNotIn((1, 2, 3), self.palette)
        self.assertEqual(self.palette.name_of(GREEN), "Green")

    def test_nearest_returns_an_exact_match_unchanged(self):
        self.assertEqual(self.palette.nearest(BLUE).rgb, BLUE)

    def test_nearest_is_perceptual_not_naive(self):
        # A dark red must not land on black just because it is dark.
        self.assertEqual(self.palette.nearest((180, 30, 30)).rgb, RED)

    def test_without_removes_candidates(self):
        reduced = self.palette.without({(255, 255, 255)})
        self.assertEqual(len(reduced), 4)
        self.assertNotIn((255, 255, 255), reduced)
        # And near-white now has to go somewhere else.
        self.assertNotEqual(reduced.nearest((250, 250, 250)).rgb, (255, 255, 255))

    def test_without_refuses_to_empty_the_palette(self):
        with self.assertRaises(PaletteError):
            self.palette.without(self.palette.colors)

    def test_reads_hex_files(self):
        path = write(self.root, "p.hex", "#c82828\n40c828\n")
        palette = Palette.from_file(path)
        self.assertEqual([s.rgb for s in palette], [(200, 40, 40), (64, 200, 40)])

    def test_rejects_unknown_format(self):
        with self.assertRaises(PaletteError):
            Palette.from_file(write(self.root, "p.psd", "x"))

    def test_hex_round_trip(self):
        self.assertEqual(parse_hex("#c82828"), RED)
        self.assertEqual(to_hex(RED), "#c82828")


class TestQuantize(TempCase):
    def test_snap_maps_everything_into_the_palette(self):
        image = Image.new("RGBA", (4, 1))
        image.putdata([(199, 41, 39, 255), (0, 0, 0, 255),
                       (41, 199, 41, 255), (0, 0, 0, 0)])
        snapped = quantize.snap(image, self.palette)
        for rgb in quantize.unique_colors(snapped):
            self.assertIn(rgb, self.palette)

    def test_snap_preserves_alpha(self):
        image = Image.new("RGBA", (2, 1))
        image.putdata([(199, 41, 39, 255), (10, 10, 10, 0)])
        snapped = quantize.snap(image, self.palette)
        self.assertEqual(snapped.getpixel((0, 0))[3], 255)
        self.assertEqual(snapped.getpixel((1, 0))[3], 0)

    def test_off_palette_reports_only_strays(self):
        image = Image.new("RGBA", (2, 1))
        image.putdata([(*RED, 255), (7, 7, 7, 255)])
        strays = quantize.off_palette(image, self.palette)
        self.assertEqual(list(strays), [(7, 7, 7)])


class TestResample(TempCase):
    def test_mode_downscale_invents_no_colours(self):
        image = Image.new("RGBA", (4, 4))
        image.putdata([(*RED, 255)] * 8 + [(*BLUE, 255)] * 8)
        small = resample.mode_downscale(image, (2, 2))
        for rgb in quantize.unique_colors(small):
            self.assertIn(rgb, {RED, BLUE})

    def test_mode_downscale_takes_the_majority(self):
        image = Image.new("RGBA", (2, 2))
        image.putdata([(*RED, 255), (*RED, 255), (*RED, 255), (*BLUE, 255)])
        small = resample.mode_downscale(image, (1, 1))
        self.assertEqual(small.getpixel((0, 0))[:3], RED)

    def test_mode_downscale_is_deterministic_on_a_tie(self):
        image = Image.new("RGBA", (2, 1))
        image.putdata([(*RED, 255), (*BLUE, 255)])
        first = resample.mode_downscale(image, (1, 1)).getpixel((0, 0))
        for _ in range(5):
            self.assertEqual(resample.mode_downscale(image, (1, 1)).getpixel((0, 0)), first)

    def test_detects_an_integer_upscale(self):
        self.assertEqual(resample.detect_integer_upscale(
            resample.integer_upscale(patterned((3, 3)), 4)), 4)

    def test_a_flat_image_reports_its_largest_factor(self):
        # True and unhelpful, and worth pinning so it is a known property rather
        # than a surprise: a solid 12x12 really is a 12x doubling of one pixel.
        self.assertEqual(resample.detect_integer_upscale(solid((12, 12), RED)), 12)

    def test_detects_nothing_when_not_blocked(self):
        image = Image.new("RGBA", (2, 2))
        image.putdata([(*RED, 255), (*BLUE, 255), (*GREEN, 255), (*RED, 255)])
        self.assertIsNone(resample.detect_integer_upscale(image))

    def test_fit_canvas_pads_without_resampling(self):
        fitted = resample.fit_canvas(solid((2, 2), RED), (4, 4))
        self.assertEqual(fitted.size, (4, 4))
        self.assertEqual(fitted.getpixel((1, 1))[:3], RED)
        self.assertEqual(fitted.getpixel((0, 0))[3], 0)

    def test_fit_canvas_anchors(self):
        fitted = resample.fit_canvas(solid((2, 2), RED), (4, 4), "bottom")
        self.assertEqual(fitted.getpixel((1, 3))[:3], RED)
        self.assertEqual(fitted.getpixel((1, 0))[3], 0)

    def test_fit_canvas_crops_when_oversized(self):
        self.assertEqual(resample.fit_canvas(solid((6, 6), RED), (2, 2)).size, (2, 2))


class TestAlpha(TempCase):
    def test_harden_makes_alpha_binary(self):
        image = Image.new("RGBA", (3, 1))
        image.putdata([(*RED, 10), (*RED, 200), (*RED, 128)])
        hardened = alpha.harden(image)
        self.assertEqual([p[3] for p in read(hardened)], [0, 255, 255])

    def test_soft_pixels_counts_only_partial(self):
        image = Image.new("RGBA", (3, 1))
        image.putdata([(*RED, 0), (*RED, 255), (*RED, 90)])
        self.assertEqual(alpha.soft_pixels(image), 1)

    def test_key_color_within_tolerance(self):
        image = Image.new("RGBA", (2, 1))
        image.putdata([(255, 0, 255, 255), (250, 5, 250, 255)])
        keyed = alpha.key_color(image, (255, 0, 255), tolerance=10)
        self.assertEqual([p[3] for p in read(keyed)], [0, 0])

    def test_connected_regions_counts_islands(self):
        image = Image.new("RGBA", (5, 1))
        image.putdata([(*RED, 255), (*RED, 255), (0, 0, 0, 0),
                       (*RED, 255), (*RED, 255)])
        self.assertEqual(alpha.connected_regions(image), 2)

    def test_connected_regions_is_four_connected(self):
        # Diagonal touch is NOT connection -- this is the case that caught a
        # detached plume that looked attached at every zoom a human reviews at.
        image = Image.new("RGBA", (2, 2))
        image.putdata([(*RED, 255), (0, 0, 0, 0), (0, 0, 0, 0), (*RED, 255)])
        self.assertEqual(alpha.connected_regions(image), 2)

    def test_guess_background_declines_when_ambiguous(self):
        image = Image.new("RGBA", (6, 6))
        image.putdata([(*RED, 255) if index % 2 else (*BLUE, 255) for index in range(36)])
        self.assertIsNone(alpha.guess_background(image))


class TestCleanOrdering(TempCase):
    def _noisy(self, size=(16, 16)):
        """An image whose every pixel is a slightly different near-red."""
        image = Image.new("RGBA", size)
        image.putdata([(190 + (i % 12), 35 + (i % 9), 35 + (i % 7), 255)
                       for i in range(size[0] * size[1])])
        return image

    def test_result_holds_only_palette_colours(self):
        result = clean_module.clean(self._noisy(), self.palette, size=(4, 4))
        for rgb in quantize.unique_colors(result.image):
            self.assertIn(rgb, self.palette)

    def test_result_is_exactly_the_canvas(self):
        result = clean_module.clean(self._noisy(), self.palette, size=(4, 4))
        self.assertEqual(result.image.size, (4, 4))

    def test_quantizing_before_downscaling_is_what_makes_mode_work(self):
        """The ordering claim, as a test rather than a comment.

        Downscale-then-quantize on noisy input has no majority to find, so the
        block winner is whatever arbitrary near-red happened to be counted first.
        Quantize-then-downscale collapses the block to one colour first, and the
        majority becomes real.
        """
        noisy = self._noisy((8, 8))
        wrong_way = quantize.snap(resample.mode_downscale(noisy, (1, 1)), self.palette)
        right_way = resample.mode_downscale(quantize.snap(noisy, self.palette), (1, 1))
        self.assertEqual(right_way.getpixel((0, 0))[:3], RED)
        # Both land in the palette; only the second is a majority rather than a
        # sample of one pixel out of sixty-four.
        self.assertIn(wrong_way.getpixel((0, 0))[:3], self.palette.colors)

    def test_alpha_stays_binary_through_the_whole_pipeline(self):
        image = Image.new("RGBA", (8, 8))
        image.putdata([(*RED, i * 4 % 256) for i in range(64)])
        result = clean_module.clean(image, self.palette, size=(4, 4))
        self.assertEqual({p[3] for p in read(result.image)} - {0, 255}, set())

    def test_contain_never_crops(self):
        """A tall subject must letterbox, not lose its top."""
        image = Image.new("RGBA", (10, 40), (0, 0, 0, 0))
        for y in range(40):
            image.putpixel((5, y), (*RED, 255))
        result = clean_module.clean(image, self.palette, size=(8, 8))
        self.assertEqual(result.image.size, (8, 8))
        self.assertGreater(sum(1 for p in read(result.image) if p[3]), 0)


class TestConfig(TempCase):
    def _config(self, extra: str = "") -> Config:
        write(self.root, "pixelforge.toml", """
            [palette]
            source = "palette.gpl"

            [[canvas]]
            name = "sprite"
            size = [4, 4]
            paths = ["art/**/*.png"]
            exclude = ["art/legacy/**"]
            max_colors = 3
        """ + extra)
        return Config.load(self.root / "pixelforge.toml")

    def test_loads_palette_relative_to_the_config(self):
        self.assertEqual(len(self._config().palette), 5)

    def test_canvas_matches_and_excludes(self):
        config = self._config()
        canvas = config.canvas_named("sprite")
        self.assertTrue(canvas.matches("art/a/b.png"))
        self.assertFalse(canvas.matches("art/legacy/b.png"))

    def test_missing_palette_is_a_clear_error(self):
        write(self.root, "bad.toml", '[palette]\nsource = "nope.gpl"\n')
        with self.assertRaises(ConfigError):
            Config.load(self.root / "bad.toml")

    def test_canvasless_config_is_refused(self):
        write(self.root, "bad.toml", '[palette]\nsource = "palette.gpl"\n')
        with self.assertRaises(ConfigError):
            Config.load(self.root / "bad.toml")

    def test_frame_size_divides(self):
        config = self._config("""
            [[canvas]]
            name = "strip"
            size = [16, 4]
            frames = 4
            paths = ["strip/*.png"]
        """)
        self.assertEqual(config.canvas_named("strip").frame_size, (4, 4))

    def test_reserved_ramps_are_path_scoped(self):
        config = self._config("""
            [[palette.reserved]]
            name = "Special"
            colors = ["#ffffff"]
            allow_in = ["art/ui/**"]
        """)
        ramp = config.reserved[0]
        self.assertTrue(ramp.permits("art/ui/panel.png"))
        self.assertFalse(ramp.permits("art/sprites/hero_idle_01.png"))
        self.assertEqual(clean_module.forbidden_colors(config, "art/sprites/hero_idle_01.png"),
                         {(255, 255, 255)})
        self.assertEqual(clean_module.forbidden_colors(config, "art/ui/panel.png"), set())


class TestLint(TempCase):
    def setUp(self) -> None:
        super().setUp()
        write(self.root, "pixelforge.toml", """
            [palette]
            source = "palette.gpl"

            [[canvas]]
            name = "sprite"
            size = [4, 4]
            paths = ["art/*.png"]
            max_colors = 2
            single_region = true
        """)
        self.config = Config.load(self.root / "pixelforge.toml")
        self.canvas = self.config.canvas_named("sprite")
        (self.root / "art").mkdir(exist_ok=True)

    def _lint(self, image: Image.Image, name: str = "a.png"):
        path = self.root / "art" / name
        image.save(path, "PNG")
        return {f.rule for f in lint.lint_file(path, self.config, self.canvas)}

    def test_clean_asset_reports_nothing(self):
        self.assertEqual(self._lint(solid((4, 4), RED)), set())

    def test_catches_off_palette(self):
        self.assertIn("off-palette", self._lint(solid((4, 4), (1, 2, 3))))

    def test_catches_wrong_canvas_size(self):
        self.assertIn("canvas-size", self._lint(solid((5, 5), RED)))

    def test_names_the_upscale_factor_in_the_size_message(self):
        path = self.root / "art" / "big.png"
        resample.integer_upscale(patterned((4, 4)), 3).save(path, "PNG")
        findings = lint.lint_file(path, self.config, self.canvas)
        message = next(f.message for f in findings if f.rule == "canvas-size")
        self.assertIn("3x pixel-doubling", message)

    def test_catches_soft_alpha(self):
        image = Image.new("RGBA", (4, 4), (*RED, 128))
        self.assertIn("soft-alpha", self._lint(image))

    def test_catches_colour_budget(self):
        image = Image.new("RGBA", (4, 4))
        image.putdata([(*RED, 255)] * 4 + [(*GREEN, 255)] * 4
                      + [(*BLUE, 255)] * 4 + [(255, 255, 255, 255)] * 4)
        self.assertIn("colour-budget", self._lint(image))

    def test_catches_detached_regions(self):
        image = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        image.putpixel((0, 0), (*RED, 255))
        image.putpixel((3, 3), (*RED, 255))
        self.assertIn("regions", self._lint(image))

    def test_missing_art_warns_and_never_errors(self):
        report = lint.lint(self.config, self.canvas, [])
        self.assertTrue(report.ok)


class TestDocumentedExamples(TempCase):
    """The README block and the `init` template must actually load.

    Both are configuration a user copies verbatim, so a drift between them and
    the loader is a broken first five minutes. Extracting them from the real
    sources rather than restating them here is the point.
    """

    def _load(self, toml_text: str) -> Config:
        write(self.root, "pixelforge.toml", toml_text)
        # Every example points its palette somewhere; put a real one there.
        source = [line for line in toml_text.splitlines()
                  if line.strip().startswith("source =")][0]
        relative = source.split("=", 1)[1].split("#")[0].strip().strip('"')
        write(self.root, relative, GPL)
        return Config.load(self.root / "pixelforge.toml")

    def test_readme_example_loads(self):
        readme = Path(__file__).resolve().parent.parent / "README.md"
        if not readme.exists():
            self.skipTest("README.md is not present in an installed package")
        blocks = readme.read_text(encoding="utf-8").split("```toml")
        self.assertGreater(len(blocks), 1, "README has no toml example to check")
        config = self._load(blocks[1].split("```")[0])
        names = [canvas.name for canvas in config.canvases]
        self.assertEqual(names, ["portrait", "walk_cycle", "tile"])
        self.assertEqual(config.canvas_named("walk_cycle").frame_size, (32, 32))
        self.assertEqual(config.canvas_named("walk_cycle").anchor, "bottom")
        self.assertTrue(config.reserved[0].permits("art/ui/panel.png"))
        self.assertFalse(config.reserved[0].permits("art/tiles/grass_plain_01.png"))

    def test_init_template_loads(self):
        from pixelforge.cli import STARTER

        config = self._load(STARTER)
        self.assertEqual([canvas.name for canvas in config.canvases], ["sprite"])
        self.assertEqual(config.canvas_named("sprite").size, (32, 32))

    def test_examples_name_no_particular_project(self):
        """Guards against a real project's folder tree leaking into the docs."""
        from pixelforge.cli import STARTER

        readme = Path(__file__).resolve().parent.parent / "README.md"
        text = STARTER + (readme.read_text(encoding="utf-8") if readme.exists() else "")
        for token in ("skeleton", "crew_portrait", "crew_sprite"):
            self.assertNotIn(token, text.lower(),
                             "%r looks like it came from one specific project" % token)


class TestPrompt(TempCase):
    def test_prompt_carries_the_real_palette_and_size(self):
        write(self.root, "pixelforge.toml", """
            [palette]
            source = "palette.gpl"

            [[canvas]]
            name = "sprite"
            size = [8, 8]
            paths = ["art/*.png"]
            max_colors = 3

            [generate]
            render_scale = 8
        """)
        config = Config.load(self.root / "pixelforge.toml")
        text = prompt.build(config, config.canvas_named("sprite"), "a lantern")
        self.assertIn("a lantern", text)
        self.assertIn("#c82828", text)          # from the palette file, not a template
        self.assertIn("8 by 8 art-pixels", text)
        self.assertIn("64 by 64 pixels", text)  # 8 art-pixels at 8x
        self.assertIn("at most 3", text)
        self.assertIn("8x8 block", text.replace("8x8", "8x8"))


if __name__ == "__main__":
    unittest.main()
