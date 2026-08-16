---
name: pixel-art
description: Use when working with pixel art assets in a project that has a pixelforge.toml — checking art against a fixed palette, cleaning generated or scanned images onto an exact canvas, previewing silhouettes, or generating new placeholder art. Also use when art fails a palette, canvas-size or transparency check.
---

# Pixel art with pixelforge

This project pins its art to a **fixed palette** and **fixed canvases**, declared in
`pixelforge.toml` at the repository root. Read that file first — it names the
palette, the canvas sizes, the colour budgets and any reserved ramps. Do not
restate those values anywhere; the config is the source of truth.

Run everything as `python -m pixelforge …` if the `pixelforge` script is not on
PATH.

## Before changing any art

```bash
pixelforge lint
```

Errors mean the asset is wrong. Warnings mean it is unfinished — on a project
where art is drawn in parallel with code, **missing art is never an error**, so do
not "fix" a warning by inventing an asset.

## Cleaning an image onto a canvas

```bash
pixelforge clean <source> --canvas <name> -o <destination> --dry-run
```

Always `--dry-run` first and read the remap table. It lists every colour that will
move and where it will land. A silent colour change to somebody's art is worse
than a refusal, so show the table to the user before writing.

The pipeline is: key background and harden alpha → snap to palette → mode
downscale → fit canvas. **That order is load-bearing** and is explained in the
package README; do not reorder it or substitute `Image.resize` for the downscale.

## Looking at the result

```bash
pixelforge sheet <file> -o preview.png --scale 8
```

Renders the art beside its **silhouette**. Read the silhouette, not just the
colour version — missing limbs and detached pieces are invisible in colour and
obvious in black. Then actually open the preview and look at it before reporting
that something is fine.

## Generating

```bash
pixelforge prompt "<subject>" --canvas <name>     # no key, no network
pixelforge gen "<subject>" --canvas <name>
```

`prompt` prints what would be sent, built from the project's own palette file.
`gen` needs `GEMINI_API_KEY` and costs money — **confirm with the user before
running it**, and never run it in a loop.

Generated art lands in the staging directory and **never in the asset tree**.
Promoting it is the user's decision, and the provenance row must record it as
AI-generated when they do.

## Rules that are easy to get wrong

- **Never** use `Image.quantize(colors=N)`. That builds an adaptive palette — the
  opposite of snapping to a fixed one. It also dithers by default.
- **Never** resize pixel art with any filter but `NEAREST`, and only by whole
  numbers.
- **Never** save an upscaled preview into the asset tree. True size is the asset.
- A reserved ramp is reserved for a reason. If `clean` reports holding colours
  back, that is correct behaviour, not a defect.
