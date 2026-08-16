"""``pixelforge`` on the command line.

Also runnable as ``python -m pixelforge``, because an entry-point script does not
always land on PATH and a tool you cannot invoke is not a tool.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from . import __version__, clean as clean_module, lint as lint_module, prompt as prompt_module
from . import providers, sheet as sheet_module
from .config import Config, ConfigError
from .palette import PaletteError, parse_hex

STARTER = '''# pixelforge -- https://github.com/amramos/pixelforge
#
# Everything project-specific lives here. Point it at the palette file the artist
# actually loads, then declare one [[canvas]] per class of asset.

[palette]
source = "assets/art/palette.gpl"    # .gpl, .hex, .txt, .act, or a PNG strip
metric = "redmean"                   # or "rgb"

# Colours that may only appear in some places. Optional.
# [[palette.reserved]]
# name = "SIGNAL"
# colors = ["#c23a2b", "#4fa84a"]
# allow_in = ["assets/art/ui/**"]

[[canvas]]
name = "sprite"
size = [32, 32]
paths = ["assets/art/sprites/**/*.png"]
max_colors = 16
hard_alpha = true
anchor = "bottom"

# [naming]
# pattern = '^[a-z]+_[a-z0-9]+_\\d{2}\\.png$'
# exempt = ["assets/art/_sources/**"]

# [provenance]
# manifest = "assets/PROVENANCE.csv"
# ai_origin_value = "ai-generated"

[generate]
provider = "gemini"
model = "gemini-2.5-flash-image"
staging = ".pixelforge/staging"
render_scale = 16
background = "#ff00ff"
style = ""
'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pixelforge",
        description="Palette-locked pixel art tooling: lint, clean, preview, generate.",
    )
    parser.add_argument("--version", action="version", version="pixelforge " + __version__)
    parser.add_argument("-c", "--config", type=Path, help="path to pixelforge.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="write a starter pixelforge.toml")

    check = sub.add_parser("lint", help="check assets against the palette and canvases")
    check.add_argument("paths", nargs="*", type=Path, help="files (default: every canvas)")
    check.add_argument("--canvas", help="only this canvas")
    check.add_argument("--strict", action="store_true", help="treat warnings as failures")

    fix = sub.add_parser("clean", help="snap to palette, harden alpha, fit the canvas")
    fix.add_argument("paths", nargs="+", type=Path)
    fix.add_argument("-o", "--out", type=Path, required=True, help="output file or directory")
    fix.add_argument("--canvas", help="canvas to clean for")
    fix.add_argument("--key", help="background colour to make transparent, e.g. #ff00ff")
    fix.add_argument("--tolerance", type=int, default=24)
    fix.add_argument("--no-trim", action="store_true", help="keep transparent margins")
    fix.add_argument("--dry-run", action="store_true", help="report without writing")

    look = sub.add_parser("sheet", help="render a preview: colour, silhouette, contact sheet")
    look.add_argument("paths", nargs="+", type=Path)
    look.add_argument("-o", "--out", type=Path, required=True)
    look.add_argument("--scale", type=int, default=8)
    look.add_argument("--columns", type=int, default=0)
    look.add_argument("--mode", choices=("review", "grid", "silhouette"), default="review")

    say = sub.add_parser("prompt", help="print the generation prompt without calling anything")
    say.add_argument("subject", help="what to draw")
    say.add_argument("--canvas", required=True)
    say.add_argument("--style", default="")

    make = sub.add_parser("gen", help="generate, then clean into the staging directory")
    make.add_argument("subject")
    make.add_argument("--canvas", required=True)
    make.add_argument("--style", default="")
    make.add_argument("--count", type=int, default=1)
    make.add_argument("--reference", type=Path, help="image to steer composition")
    make.add_argument("--api-key")
    make.add_argument("--raw", action="store_true", help="also keep the untouched response")

    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (ConfigError, PaletteError, providers.GenerationError) as failure:
        print("error: %s" % failure, file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        return _init()

    config = Config.load(args.config)
    if args.command == "lint":
        return _lint(config, args)
    if args.command == "clean":
        return _clean(config, args)
    if args.command == "sheet":
        return _sheet(args)
    if args.command == "prompt":
        canvas = config.canvas_named(args.canvas)
        print(prompt_module.build(config, canvas, args.subject, args.style))
        return 0
    if args.command == "gen":
        return _gen(config, args)
    return 2


def _init() -> int:
    target = Path.cwd() / "pixelforge.toml"
    if target.exists():
        print("error: %s already exists" % target, file=sys.stderr)
        return 2
    target.write_text(STARTER, encoding="utf-8")
    print("wrote %s -- point [palette] source at your palette file next" % target)
    return 0


def _lint(config: Config, args: argparse.Namespace) -> int:
    canvas = config.canvas_named(args.canvas) if args.canvas else None
    paths = [p.resolve() for p in args.paths] if args.paths else None
    report = lint_module.lint(config, canvas, paths)

    for finding in report.findings:
        print(finding.format())
    print("\n%d file(s) checked, %d error(s), %d warning(s)"
          % (report.checked, len(report.errors), len(report.warnings)))
    if not report.findings:
        print("clean.")
    failed = bool(report.errors) or (args.strict and bool(report.warnings))
    return 1 if failed else 0


def _clean(config: Config, args: argparse.Namespace) -> int:
    canvas = config.canvas_named(args.canvas) if args.canvas else None
    key = parse_hex(args.key) if args.key else None
    many = len(args.paths) > 1
    if many and args.out.suffix:
        print("error: --out must be a directory when cleaning several files", file=sys.stderr)
        return 2

    for source in args.paths:
        profile = canvas or config.canvas_for(source.resolve())
        with Image.open(source) as handle:
            image = handle.convert("RGBA")
        options = {"key": key, "tolerance": args.tolerance, "trim": not args.no_trim}
        destination = (args.out / source.name) if (many or not args.out.suffix) else args.out
        if profile is None:
            result = clean_module.clean(image, config.palette, **options)
        else:
            result = clean_module.clean_for(
                config, image, profile, config.relative(destination), **options)

        print("%s -> %s" % (source, destination))
        print(result.summary() or "  - nothing to do")
        if result.remap:
            print("  remap:")
            for line in result.remap:
                print("  " + line)
        if args.dry_run:
            print("  (dry run, nothing written)")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        result.image.save(destination, "PNG")
    return 0


def _sheet(args: argparse.Namespace) -> int:
    images = []
    for path in args.paths:
        with Image.open(path) as handle:
            images.append(handle.convert("RGBA"))

    if args.mode == "review" and len(images) == 1:
        output = sheet_module.review(images[0], args.scale)
    elif args.mode == "silhouette":
        output = sheet_module.contact_sheet(
            [sheet_module.silhouette(image) for image in images],
            args.columns, args.scale)
    else:
        output = sheet_module.contact_sheet(
            [sheet_module.on_background(image, (45, 85, 102)) for image in images],
            args.columns, args.scale)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    output.save(args.out, "PNG")
    print("wrote %s (%dx%d)" % (args.out, *output.size))
    return 0


def _gen(config: Config, args: argparse.Namespace) -> int:
    canvas = config.canvas_named(args.canvas)
    text = prompt_module.build(config, canvas, args.subject, args.style)
    provider = providers.get(config.generation.provider)(
        model=config.generation.model, api_key=args.api_key)

    print("%s | %s" % (config.generation.model, prompt_module.describe(config, canvas)))
    result = provider.generate(text, args.reference, args.count)
    print("received %d image(s)" % len(result))

    staging = config.root / config.generation.staging
    staging.mkdir(parents=True, exist_ok=True)
    stem = _slug(args.subject)
    key = parse_hex(config.generation.background)

    for index, blob in enumerate(result.images, start=1):
        raw_path = staging / ("%s_%02d_raw.png" % (stem, index))
        raw_path.write_bytes(blob)
        with Image.open(raw_path) as handle:
            image = handle.convert("RGBA")
        cleaned = clean_module.clean_for(config, image, canvas, key=key)
        out_path = staging / ("%s_%02d.png" % (stem, index))
        cleaned.image.save(out_path, "PNG")
        if not args.raw:
            raw_path.unlink()

        print("\n%s" % out_path)
        print(cleaned.summary())
        for finding in lint_module.lint_file(out_path, config, canvas):
            print("  " + finding.format().replace("\n", "\n  "))

    print("\nStaged in %s. Nothing was written into your asset tree; promote "
          "deliberately, and record the provenance row when you do." % staging)
    return 0


def _slug(text: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in text.lower())
    return "_".join(part for part in cleaned.split("_") if part)[:48] or "asset"


if __name__ == "__main__":
    sys.exit(main())
