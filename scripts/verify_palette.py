#!/usr/bin/env python3
"""Palette accessibility gate.

The four task colours are not decoration. A clinician reads the segmentation timeline by colour
before reading any label, and the model's worst confusion is stair-descent against level walking
-- so a palette in which DNS and WAK are hard to tell apart would hide the system's known
weakness behind a colour choice. That makes the palette a correctness property, and correctness
properties belong in CI.

This script fails the build if:

  * any fill that carries white text drops below WCAG AA contrast (4.5:1),
  * any two task colours become hard to separate under normal, deuteranopic or protanopic
    vision, or
  * the DNS/WAK pair specifically falls below a much stricter floor.

Colour-vision deficiency is simulated with the Vienot, Brettel & Mollon (1999) LMS-plane
projection. Separation is measured in CIEDE2000, which is perceptually uniform enough that one
threshold means the same thing across the whole gamut: a delta-E near 1 is the just-noticeable
difference, and below about 10 two large flat fills start to read as the same colour.

Usage::

    python scripts/verify_palette.py           # from the repository root
    python scripts/verify_palette.py --table   # print the full matrix, then check
"""

from __future__ import annotations

import argparse
import itertools
import math

# --------------------------------------------------------------------------------------------
# The palette. Task colours are the ONLY saturated fills in the product; status is expressed as
# a tinted chip with an icon and a word, in a lower-chroma register, and therefore does not
# compete with these for hue. See docs/DESIGN_TOKENS.md for why that separation exists.
# --------------------------------------------------------------------------------------------
TASK = {
    "task/wak": "#1D4ED8",    # level walking
    "task/ups": "#115E59",    # stair ascent
    "task/dns": "#B4400F",    # stair descent
    "task/stdup": "#701A75",  # sit to stand
}
STATUS = {
    "status/flag": "#7F1D1D",  # refusal  - the system will not proceed
    "status/warn": "#B45309",  # advisory - the system proceeds, with a named caveat
    "status/ok": "#15803D",    # verified, sufficient, approved
}
BRAND = {"brand/primary": "#0F5C73"}

WHITE = "#FFFFFF"

MIN_CONTRAST = 4.5           # WCAG 2.1 AA, normal text
MIN_TASK_SEPARATION = 12.0   # any two task fills, under common vision types
MIN_DNS_WAK = 30.0           # the pair the model confuses: held to a much stricter floor
COMMON_VISION = ("normal", "deuteranopia", "protanopia")
ALL_VISION = (*COMMON_VISION, "tritanopia")


# ---------------------------------------------- colour space
def hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _linear(c):
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


def _delinear(c):
    return tuple(
        12.92 * v if v <= 0.0031308 else 1.055 * (max(v, 0.0) ** (1 / 2.4)) - 0.055 for v in c
    )


def contrast(a: str, b: str) -> float:
    def lum(h):
        r, g, bl = _linear(hex_rgb(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl

    hi, lo = max(lum(a), lum(b)), min(lum(a), lum(b))
    return (hi + 0.05) / (lo + 0.05)


def _lab(rgb):
    r, g, b = _linear(rgb)
    X = 0.4124 * r + 0.3576 * g + 0.1805 * b
    Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    Z = 0.0193 * r + 0.1192 * g + 0.9505 * b

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(X / 0.95047), f(Y / 1.0), f(Z / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(rgb1, rgb2) -> float:
    L1, a1, b1 = _lab(rgb1)
    L2, a2, b2 = _lab(rgb2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb**7 / (Cb**7 + 25**7))) if Cb > 0 else 0.5
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    T = (
        1
        - 0.17 * math.cos(math.radians(hbp - 30))
        + 0.24 * math.cos(math.radians(2 * hbp))
        + 0.32 * math.cos(math.radians(3 * hbp + 6))
        - 0.20 * math.cos(math.radians(4 * hbp - 63))
    )
    Rc = 2 * math.sqrt(Cbp**7 / (Cbp**7 + 25**7)) if Cbp > 0 else 0.0
    Sl = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * (30 * math.exp(-(((hbp - 275) / 25) ** 2))))) * Rc
    return math.sqrt(
        (dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh)
    )


# ---------------------------------------------- dichromacy (Vienot, Brettel & Mollon 1999)
_RGB2LMS = ((17.8824, 43.5161, 4.11935), (3.45565, 27.1554, 3.86714), (0.0299566, 0.184309, 1.46709))
_LMS2RGB = (
    (0.080944, -0.130504, 0.116721),
    (-0.0102485, 0.0540194, -0.113615),
    (-0.000365294, -0.00412163, 0.693513),
)
_SIM = {
    "protanopia": ((0, 2.02344, -2.52581), (0, 1, 0), (0, 0, 1)),
    "deuteranopia": ((1, 0, 0), (0.494207, 0, 1.24827), (0, 0, 1)),
    "tritanopia": ((1, 0, 0), (0, 1, 0), (-0.395913, 0.801109, 0)),
}


def _mul(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def as_seen(hex_colour: str, vision: str):
    """The colour as a person with the named vision type perceives it."""
    rgb = hex_rgb(hex_colour)
    if vision == "normal":
        return rgb
    return _delinear(_mul(_LMS2RGB, _mul(_SIM[vision], _mul(_RGB2LMS, _linear(rgb)))))


def separation(a: str, b: str, vision: str) -> float:
    return ciede2000(as_seen(a, vision), as_seen(b, vision))


# ---------------------------------------------- the checks
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", action="store_true", help="print the full matrix first")
    args = parser.parse_args()

    failures: list[str] = []
    everything = {**TASK, **STATUS, **BRAND}

    if args.table:
        print(f"{'pair':32s}" + "".join(f"{v[:9]:>11s}" for v in ALL_VISION))
        print("-" * 76)
        for a, b in itertools.combinations(TASK, 2):
            row = "".join(f"{separation(TASK[a], TASK[b], v):11.1f}" for v in ALL_VISION)
            mark = "  <- model confuses these" if {a, b} == {"task/dns", "task/wak"} else ""
            print(f"{a.split('/')[1] + ' / ' + b.split('/')[1]:32s}{row}{mark}")
        print()

    for name, colour in everything.items():
        ratio = contrast(colour, WHITE)
        if ratio < MIN_CONTRAST:
            failures.append(
                f"{name} ({colour}) is {ratio:.2f}:1 against white text, below the {MIN_CONTRAST}:1 "
                f"WCAG AA floor."
            )

    for a, b in itertools.combinations(TASK, 2):
        for vision in COMMON_VISION:
            d = separation(TASK[a], TASK[b], vision)
            if d < MIN_TASK_SEPARATION:
                failures.append(
                    f"{a} and {b} are only dE {d:.1f} apart under {vision} "
                    f"(floor {MIN_TASK_SEPARATION}). Two task fills that close read as one."
                )

    for vision in ALL_VISION:
        d = separation(TASK["task/dns"], TASK["task/wak"], vision)
        if d < MIN_DNS_WAK:
            failures.append(
                f"DNS and WAK are only dE {d:.1f} apart under {vision} (floor {MIN_DNS_WAK}). "
                f"These are the two classes the model confuses most; a palette that merges them "
                f"hides the system's known weakness behind a colour choice."
            )

    if failures:
        print("FAIL  the palette does not meet its accessibility contract.\n")
        for f in failures:
            print(f"  - {f}")
        print(f"\n{len(failures)} problem(s). See docs/DESIGN_TOKENS.md.")
        return 1

    weakest_common = min(
        separation(TASK[a], TASK[b], v)
        for a, b in itertools.combinations(TASK, 2)
        for v in COMMON_VISION
    )
    dns_wak = min(separation(TASK["task/dns"], TASK["task/wak"], v) for v in ALL_VISION)
    print(
        f"OK  {len(everything)} colours clear WCAG AA on white text; weakest task pair is "
        f"dE {weakest_common:.1f} under common vision types; DNS/WAK never closer than "
        f"dE {dns_wak:.1f}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
