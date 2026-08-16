---
description: Snap an image onto the palette and an exact canvas, showing the remap first
---

Clean the image(s) the user named onto one of this project's canvases.

1. Read `pixelforge.toml` and pick the canvas that matches, or ask which one.
2. Run the dry run first and **show the user the remap table**:

```
!python -m pixelforge clean $ARGUMENTS --dry-run
```

3. Call out anything surprising — a colour moving a long way, a reserved ramp
   being held back, a large trim, or a downscale factor that will lose detail.
4. Only after the user agrees, re-run without `--dry-run`.
5. Render a preview with `pixelforge sheet` and **actually look at it** before
   telling the user it worked. Read the silhouette panel, not only the colour one.

Never write into the asset tree without the user saying so.
