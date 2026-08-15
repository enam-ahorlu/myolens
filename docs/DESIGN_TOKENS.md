# Design tokens

Source of truth: `frontend/src/styles/tokens.css`. Enforced by `scripts/verify_palette.py`,
which runs as its own CI job.

## Attribution

The visual language is adapted from the **MediCare Admin Dashboard UI Kit**, published on the
Figma Community and licensed **CC BY 4.0**. Attribution is a licence condition, not a courtesy,
so it is recorded here, in `tokens.css`, and in the third-party components section of
`DECLARATION.md`.

**What was taken:** the type family (Plus Jakarta Sans) and its four weights, the neutral ramp,
the near-monochrome surface treatment, the tight 4 px radius language, the border-over-shadow
elevation model, and the chip-based status pattern.

**What was not taken:** the palette's semantic colours, all of which were re-derived (below);
the dark theme; and every layout, which comes from MyoLens's own ten screens.

## Why this kit suits this product

The kit is nearly monochrome, white cards on a very light canvas, near-black text, borders
rather than shadows, and a single restrained accent. On most products that reads as taste. Here
it is functional: **MyoLens has four task colours that carry meaning**, and they are legible in
proportion to how little else on screen competes for colour attention. A more colourful chrome
would not merely be busier, it would make the segmentation timeline harder to read.

The kit's own primary ramp is a teal that brackets MyoLens's existing `#0F5C73`, so the brand
colour survives the re-theme unchanged.

## The task colours were derived, not chosen

| Token | Value | Task | Contrast on white text |
|---|---|---|---|
| `--task-wak` | `#1D4ED8` | Level walking | 6.70:1 |
| `--task-ups` | `#115E59` | Stair ascent | 7.58:1 |
| `--task-dns` | `#B4400F` | Stair descent | 5.71:1 |
| `--task-stdup` | `#701A75` | Sit to stand | 10.03:1 |

Separation in CIEDE2000, under simulated dichromacy (Viénot, Brettel & Mollon 1999):

| Pair | Normal | Deuteranopia | Protanopia | Tritanopia |
|---|---|---|---|---|
| WAK / UPS | 33.8 | 25.2 | 29.5 | 8.7 |
| **WAK / DNS** | **47.9** | **70.7** | **62.5** | **72.5** |
| WAK / STDUP | 23.5 | 15.6 | 16.3 | 92.0 |
| UPS / DNS | 46.5 | 34.6 | 20.8 | 62.9 |
| UPS / STDUP | 35.5 | 14.7 | 26.2 | 78.0 |
| DNS / STDUP | 40.7 | 54.0 | 53.9 | 29.6 |

A ΔE near 1 is the just-noticeable difference; below about 10, two large flat fills start to read
as the same colour.

**DNS/WAK is held to a stricter floor than every other pair, and it is the strongest pair in the
table.** That is the whole point. Stair descent is the ensemble's weakest class (F1 0.81) and its
commonest confusion is DNS mistaken for WAK. 6.6% of descent windows, even after channel dropout
and ensembling more than halved it. A palette in which those two fills looked similar
would hide the system's known weakness behind a colour choice, the reviewer would be least able
to see a distinction exactly where the model is least reliable.

### The timeline, at its faintest

A bout block is drawn over `--bg-subtle` at an opacity that encodes model confidence, so the
colour that reaches the eye is not the token's own hex but `a x task + (1 - a) x track`. Nothing
checked that until now, and the omission sat exactly where it mattered: the gate covered flat
fills, and the one component that composites its colours was added afterwards and slipped past
it. At the original floor of 0.42 every task landed between **1.89:1 and 2.25:1** against the
track, against the **3:1** WCAG 2.1 SC 1.4.11 asks of a graphical object -- so the least-confident
bout, the one a reviewer most needs to notice, was the one nearest to invisible.

The floor is now **0.70**, the point at which all four clear it (stair descent binds, at 0.695).
`verify_palette.py` recomputes the composite on every push, so it cannot drift back down quietly.

The cost is stated rather than hidden: the usable opacity range narrows from 0.58 to 0.30, so the
confidence gradient is subtler than it was. Opacity was never the only channel carrying it -- the
bout table shows mean confidence numerically and each segment's accessible name states it in
words -- and a subtle gradient beats an invisible bout.

### What the check caught

The first candidate set used violet `#6D28D9` for sit-to-stand. It passes contrast comfortably
and looks fine. Under deuteranopia it and the walking blue collapse to a **ΔE of 0.38**, the two
most frequent tasks in a session, rendered indistinguishable for roughly one man in sixteen.

This was not visible by eye on a normal-vision monitor, and it would not have been found by
review. It was found because the property was computed.

### The limit that was accepted, and stated

WAK/UPS sits at ΔE 8.7 under **tritanopia**, below the threshold applied to the common
deficiencies. Tritanopia affects on the order of 0.01% of people and is not sex-linked, and every
alternative that fixed it broke a pair under deuteranopia or protanopia, which together affect
about 8% of men. The verifier therefore enforces ΔE ≥ 12 under normal, deuteranopic and
protanopic vision, and reports tritanopia without gating on it. Bout labels are also always
present as text, so colour is never the sole carrier.

## Why status colours live in a different register

The search that produced the table above also produced a negative result worth recording: **seven
mutually separable saturated colours do not exist within the dichromatic gamut.** Every candidate
for stair ascent that cleared the other three task colours collided with the verified-green or
the advisory-amber.

Rather than keep tuning hexes, the collision was removed by construction:

- **Task colours are the only saturated fills in the product.** They appear on the segmentation
  timeline and on task badges, and nowhere else.
- **Status is a chip**, a pale tint behind dark text, always with an icon and a word
  ("Insufficient", "Refused", "Sufficient"). It is never a large saturated block.

A burnt-orange bout block and an amber-tinted pill reading "Advisory" are not confusable objects
even though their base hues are close, because they differ in size, chroma, shape, and in
carrying a word. This also satisfies the rule that refusal and advisory must never be separable
by hue alone: `#7F1D1D` and `#B45309` are 18.6 L\* apart, carry different icons, and say different
things.

It is the same pattern the source kit uses, which is a reasonable sign it is the right one.

## Type

Plus Jakarta Sans, at 400 / 500 / 600 / 700. The scale is deliberately compressed. 14 px is the
workhorse body size and 12 px carries labels, because this is a data-dense clinical tool and
vertical space on the segmentation review screen is the scarcest resource in the product.

## What is deliberately absent

**No dark theme.** Item 20 on the anti-creep list. The kit ships one; adopting it would mean
re-deriving and re-verifying every task and status colour against a dark surface, which is the
entire analysis above done a second time, for an item that carries no marks and no clinical
benefit.

**No shadow-heavy elevation.** Borders carry structure. A page of drop-shadowed cards reads as a
page of floating objects; a clinical table should read as one surface.

**No colour below 768 px**, because there is no layout below 768 px.
