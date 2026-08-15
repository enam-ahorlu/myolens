# Design Record — MyoLens

**Figma file** `MyoLens — Design System & Screens` · key `xsw1wp832BKxHNV5IFvXk8`
**Status** all ten frozen screens built and visually verified · **Date** 2026-08-13

Design was completed *before* implementation, deliberately and in contrast to the CivicConnect group project, where screens were drawn after the code existed and the design artefact was therefore a description rather than a specification. Everything in the Figma file is a decision the code is expected to honour.

---

## 1. File structure

| Page | Contents |
|---|---|
| `01 Foundations` | Colour, spacing and radius variable collections; nine Inter text styles |
| `02 Components` | Shared patterns lifted out of the screens |
| `03 Screens` | The ten frozen screens, laid out left to right in journey order |

### Screens, in the order of §11 of the plan of record

| # | Frame | Node | Height |
|---|---|---|---|
| 01 | Login | `19:2` | 806 |
| 02 | Participant list | `13:2` | 536 |
| 03 | Participant detail | `14:2` | 846 |
| 04 | Calibration upload | `8:88` | 694 |
| 05 | Session upload | `8:2` | 715 |
| 06 | Segmentation review | `2:2` | 885 |
| 07 | Results | `7:2` | 682 |
| 08 | Model card | `16:2` | 1928 |
| 09 | Admin — clinicians | `19:25` | 598 |
| 10 | Error and refusal states | `20:2` | 1066 |

All frames are 1440 wide. Every layout container is auto-layout; there is no absolute positioning below the frame level, so the screens are directly translatable to flex containers rather than being pictures of a layout.

---

## 2. Tokens

**Colour** — 24 variables in `MyoLens/Colour`. Backgrounds, borders, text, brand, four task colours, and status.

The four task colours are the load-bearing ones, because a clinician reads the segmentation strip by colour before reading any label:

| Task | Hex | Meaning |
|---|---|---|
| `task/wak` | `#1D4ED8` | Level walking |
| `task/ups` | `#0F766E` | Ascending stairs |
| `task/dns` | `#C2410C` | Descending stairs |
| `task/stdup` | `#6D28D9` | Sit-to-stand |

All four clear WCAG 2.1 AA against white text and remain separable under simulated deuteranopia — checked because DNS and WAK are the pair the model confuses most, and a palette that merges exactly those two would hide the system's known weakness behind a colour choice.

**Status colours are split by meaning, not by severity.**

- `status/flagSubtle` + `status/flag` (red) — refusals and out-of-distribution. The system will not proceed.
- `status/warnSubtle` + `status/warn` (amber) — advisory and degraded-but-supported. The system will proceed, with a named caveat.
- `status/ok` (green) — verified, sufficient, approved.

`status/warnSubtle` was added late, during the screen build. The intended-use banner had been painted with a raw `#FEF3E0` on the first three screens rather than a token, which is exactly the kind of drift a variable collection exists to prevent. The token was created, the five unbound fills were rebound to it, and a subsequent sweep cleared 80 hardcoded white fills that `figma.createAutoLayout()` had applied by default to layout containers. There are now no unbound colours on the screens page.

**Spacing** 12 steps (2–64). **Radius** 5 steps. **Text** nine styles: Display, Heading L/M/S, Body Default/Strong/Small, Label, Numeric.

---

## 3. Design decisions the code must honour

### 3.1 The intended-use banner is on every screen

Not a footer, not a modal shown once, not a tooltip. It is the second element on every screen, below the top bar and above all content, in amber, at all times. A reader who screenshots any single screen of this system and sends it to a colleague sends the disclaimer with it. This is the cheapest possible answer to the regulatory question and it costs 34 pixels.

### 3.2 Metrics are locked until a human approves

The segmentation review screen carries an explicit gate: *"Metrics are locked until you approve — no activation or co-activation metric is computed from an unreviewed segmentation."* The approve button is disabled while flagged bouts remain unresolved. This is the design expression of the whole clinical argument — an 87.6% classifier is not a finding, it is a first draft.

### 3.3 The review queue is ordered by confidence, not by time

Least confident first, explicitly labelled as such. A chronological queue would spend the clinician's attention uniformly across bouts the model is sure about. The queue's ordering is the mechanism by which a 0.858 macro-F1 becomes a usable clinical workflow, and it is stated on the screen so a reviewer can see the reasoning rather than infer it.

### 3.4 Refusal is a designed state, not an error path

Screen 10 catalogues all seven states in which MyoLens declines to proceed — 403, 409, 412, 413, 422, 423, 503 — each with its cause and what the user can do about it. Two of them (422 out-of-distribution, 409 montage rejected) are the direct product of the thesis's own findings about where the model fails silently. The screen exists so that a reviewer can see the refusals as a coherent set rather than encountering them as scattered bugs, and it ends with the guarantee that none of them writes a partial record.

### 3.5 Calibration sufficiency is drawn against a scale with a visible threshold

The sufficiency bars span 0–40 windows with a marker at 20, rather than filling to 100% at threshold. Filling at threshold makes 33 windows and 20 windows look identical, which loses the only information the bar carries. This was a real bug caught in visual verification: the bars had been sized against pre-layout rail widths and all three sufficient tasks rendered at 100% while overflowing their rails.

The DNS row on that screen is *deliberately failing* — 12 windows across 2 blocks, INSUFFICIENT — with the message: *"You can proceed. DNS will be excluded from this participant's output space and reported as unsupported, not guessed."* A design that only shows its happy path has not been designed.

### 3.6 Both accuracy regimes appear together, always

The model card shows the held-out-three figures (0.8760 ensemble, n = 3, flagged as indicative) and the LOSO figures (0.858 transductive, 0.817 causal) in two adjacent tables, with the transductive row highlighted as the reported figure and the causal row labelled *wearable*. Neither number appears anywhere in the product without the other nearby.

### 3.7 De-identification is visible on the participant list

Codes, banded age, no names, no dates of birth. The footer states it. A reviewer should not have to read the security rules to establish that the system holds no PHI.

### 3.8 The audit trail is a first-class screen element

Participant detail carries an Activity card reading straight off the audit collection, showing relabels with the model's confidence at the time of the override. The rationale is on the card: *"a system that lets a human overrule a model is only trustworthy if the overrule is visible afterwards."*

---

## 4. Layout bugs found by visual verification

Every screen was screenshotted after construction. The same classes of bug appeared repeatedly, and none of them would have been caught by reading the construction script:

| Bug | Cause | Fix |
|---|---|---|
| Approval gate collapsed to a stub | Frame created FIXED then converted to auto-layout loses child sizing | Re-set `layoutSizingHorizontal = "FILL"` after conversion |
| Wrapping text clipped | Sizing applied before `textAutoResize` | Set `textAutoResize = "HEIGHT"` *before* `layoutSizingHorizontal = "FILL"` |
| Flag chips clipped | Track height too small for the chip | Raised 72 → 96 px |
| %CAL bars not proportional | Sized against pre-layout rail widths | Second pass using settled `rail.width` |
| Sufficiency bars all full, overflowing rails | Same cause, different screen | Rescaled against settled width, added threshold marker |
| PASS chips flush against their labels | Spacer frames left FIXED at 8 px | Set spacers to FILL |
| 80 hardcoded white fills | `createAutoLayout()` paints new frames white by default | Swept and cleared |
| Model card column imbalance | Sidebar grew to ~2.4k px against a ~1k px main column | Equal-width columns, prose card moved left |

The practical lesson, and one worth stating in the report: constructing a design programmatically does not remove the need to look at it. Eight of these were invisible in the code and obvious in the render.

---

## 5. What is deliberately *not* in the design

Consistent with the anti-creep list in §7 of the plan of record:

- No bilateral or symmetry view — the montage is unilateral and no symmetry metric is derivable from it.
- No real-time or streaming view — the system analyses complete uploaded recordings, and a live view would imply the causal regime, which is a different and worse number.
- No cross-participant comparison or cohort dashboard.
- No trend chart across sessions. %CAL is normalised to each session's own calibration peak, so a between-session line would be plotting a moving denominator.
- No fifth movement class anywhere in the interface, including in empty states.
- No confidence figure presented as a probability of correctness. Confidences are shown as review-priority signals and labelled as such.
