---
description: Generate placeholder pixel art, then clean and lint it into staging
---

Generate art for this project. **This calls a paid API — confirm with the user
before running it, and never run it in a loop.**

First show what would be sent, which needs no key and no network:

```
!python -m pixelforge prompt $ARGUMENTS
```

Let the user read and adjust the prompt. The palette and canvas come from
`pixelforge.toml`, so change the config rather than pasting values into the
subject line.

Then, once they agree:

```
!python -m pixelforge gen $ARGUMENTS
```

Afterwards:

- Render a preview and **look at it**. Report honestly what is wrong with it —
  silhouette, proportion, whether the colours landed sensibly. A model will not
  honour the palette; the cleaner is what makes it compliant, and the result is
  usually structurally right and locally mushy.
- The output is in the staging directory. **Do not move it into the asset tree.**
  Promotion is the user's decision, and it needs a provenance row recording the
  art as AI-generated.
