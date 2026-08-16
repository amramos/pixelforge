---
description: Check pixel art against the project's palette, canvases and naming rules
---

Run the pixelforge linter over this project's art and report what it finds.

```
!python -m pixelforge lint $ARGUMENTS
```

Summarise the output for the user:

- Group findings by rule rather than listing every file separately.
- Errors mean the asset is wrong; warnings mean it is unfinished. Say which is
  which, and do not treat a warning as something to fix by inventing an asset.
- For `off-palette`, name the nearest legal colour the linter suggested.
- For `canvas-size`, check whether the message reports an exact N× pixel-doubling
  — if so, the fix is a downscale, not a redraw.

Do not change any file. Propose the fix and let the user decide.
