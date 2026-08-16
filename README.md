# pixelforge

Palette-locked pixel art tooling. Lint, clean, preview and generate art against a
**fixed palette** and **fixed canvases**.

Everything project-specific lives in a `pixelforge.toml`. Nothing in the package
knows about any particular game, so the same tool serves a 48×64 paperdoll and a
16×16 tileset.

```bash
pip install pixelforge
pixelforge init
pixelforge lint
```

## Why not just `Image.quantize(colors=16)`

Because that picks the sixteen colours that best represent *your image* — an
adaptive palette, which is the opposite of the job. You want the sixteen colours
that are **in your palette file**. It also dithers by default, spraying
Floyd–Steinberg checkerboard across flat regions, which is precisely what pixel
art is not.

## The ordering that matters

Cleaning a generated or scanned image runs in this order, and the order is the
whole trick:

1. **Key the background and harden alpha** — at full resolution
2. **Snap every colour to the palette** — still at full resolution
3. **Mode-downscale to the canvas** — most common colour per block
4. **Fit the canvas exactly** — crop and pad, never resample

Step 2 must come before step 3. Mode filtering only finds a majority once a block
holds a handful of palette colours instead of a few hundred near-identical ones;
run it on raw output and the winner is arbitrary — no better than `NEAREST`.

Step 1 must come before step 2, or a magenta chroma-key background gets snapped
onto the nearest red in your palette and becomes part of the art.

## Configuration

```toml
[palette]
source = "assets/art/skeleton-crew-34.gpl"   # .gpl, .hex, .txt, .act, or a PNG strip
metric = "redmean"                           # perceptual-ish; or "rgb"

[[palette.reserved]]
name = "SIGNAL"
colors = ["#c23a2b", "#4fa84a"]
allow_in = ["assets/art/ui/**"]

[[canvas]]
name = "crew_portrait"
size = [48, 64]
paths = ["assets/art/crew/portrait/**/*.png"]
max_colors = 16
hard_alpha = true

[[canvas]]
name = "crew_sprite"
size = [128, 32]
frames = 4
paths = ["assets/art/crew/sprite/**/*.png"]
max_colors = 16
anchor = "bottom"

[naming]
pattern = '^[a-z]+_[a-z0-9]+_\d{2}\.png$'
exempt = ["assets/art/_sources/**"]

[provenance]
manifest = "assets/PROVENANCE.csv"
ai_origin_value = "ai-generated"

[generate]
provider = "gemini"
model = "gemini-2.5-flash-image"
staging = ".pixelforge/staging"
render_scale = 16
background = "#ff00ff"
```

## Commands

| | |
|---|---|
| `pixelforge init` | write a starter config |
| `pixelforge lint [paths]` | check palette, alpha, canvas size, colour budget, naming, reserved ramps, connected regions, provenance |
| `pixelforge clean <paths> -o <dir>` | run the pipeline above; `--dry-run` reports the remap without writing |
| `pixelforge sheet <paths> -o out.png` | colour-beside-silhouette review, or a contact sheet |
| `pixelforge prompt <subject> --canvas <name>` | print the generation prompt — no API key, no network |
| `pixelforge gen <subject> --canvas <name>` | generate, clean, lint, and stage |

`python -m pixelforge` works identically, for when the entry-point script isn't on
PATH.

## Lint rules

| Rule | Severity | Catches |
|---|---|---|
| `off-palette` | error | any colour not in the palette, with its nearest legal match |
| `soft-alpha` | error | partially transparent pixels — anti-aliased edges, layer opacity ≠ 100% |
| `canvas-size` | error | wrong size, and reports when the file is an exact *N*× pixel-doubling |
| `colour-budget` | error | more distinct colours than the canvas allows |
| `reserved` | error | a reserved ramp used somewhere it isn't permitted |
| `regions` | error | detached opaque islands — a feather off a hat, a hand off an arm |
| `naming` | error | filename against a regex |
| `provenance` | warn | no row in the manifest |
| `unclaimed` | warn | no canvas matches this path |
| `empty` | warn | no opaque pixels |

Severity is two-valued on purpose: **error** means the asset is wrong, **warn**
means it is unfinished. On a project where art is drawn in parallel with code,
missing art must never be an error.

## Generation

`gen` builds the prompt from your palette file and canvas — not from a template
with the colours pasted in, which is how a prompt and a palette drift apart. A
model won't honour a palette exactly; it does resemblance, not lookup. Listing
the colours biases it usefully and the cleaning pipeline is what makes the output
actually compliant.

Generated files land in the staging directory and **never in your asset tree**.
Promotion is deliberate, so an `origin = ai-generated` provenance row gets
written by a human who meant it.

> The Gemini provider is **written but not verified against a live key** — there
> was no API access when it was built. The endpoint and model id are both
> configurable; if a call fails, change `[generate] model` before changing code.

## Status

Alpha. The palette, quantize, resample, alpha, lint and clean layers are tested.
The provider layer is not.

## License

MIT.
