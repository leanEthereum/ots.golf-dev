"""The forest scheme, drawn as the iris of an eye.

Root at the center; 6 subtree digests around it; 3 group digests under each; 3 hash chains of 14
beads under each group, radiating outward to their 54 secret sources. One real signature is lit on
it (revealed values, recomputed nodes, untouched beads), drawn uniformly from the disclosure family
of `Cuts.lean`: the cuts of reconstruction cost 103 with at most 42 revealed values, of the three
shapes (revealed subtrees, revealed groups, chain cost) = (1, 2, 83), (0, 6, 83), (1, 3, 84).
Every element carries its role and indices as data attributes, so the page's script can light a
fresh uniform signature while the eye is closed and draw its verification as current flowing from
the revealed values to the root; the server-rendered signature, fully lit, is the frame without script.
The eye's volume (shaded sclera, iris gradient and fibres, soft pupil, lid shade, catchlights) uses
gradients defined once in <defs>, their colours set by the stylesheet's `--art-*` tokens per theme.
"""
from __future__ import annotations

import math
from functools import lru_cache

CHAINS, LEN, PER_G, PER_E, NUM_E = 54, 14, 3, 3, 6
SHAPES = ((1, 2, 83), (0, 6, 83), (1, 3, 84))        # (|E|, |G|, chain cost); root 2 + digests + chains = 103
CX, CY = 430, 280
# Leave space for the pupil while retaining the scheme's radial ordering.
R_E, R_G, R_TIP, STEP = 73.64, 97.2, 120, 5.89


def angle(chain: int) -> float:
    return -math.pi / 2 + 2 * math.pi * chain / CHAINS


def polar(r: float, a: float) -> tuple[float, float]:
    return CX + r * math.cos(a), CY + r * math.sin(a)


@lru_cache(maxsize=1)
def ways() -> list[list[int]]:
    """ways[n][s]: the number of ways to spend `s` chain hashes on `n` chains, each 0..14."""
    top = max(c for _, _, c in SHAPES)
    w = [[0] * (top + 1) for _ in range(CHAINS + 1)]
    w[0][0] = 1
    for n in range(1, CHAINS + 1):
        for s in range(top + 1):
            w[n][s] = sum(w[n - 1][s - c] for c in range(0, min(LEN, s) + 1))
    return w


def active_chains(e: int, g: int) -> int:
    return CHAINS - PER_G * PER_E * e - PER_G * g


def shape_weights() -> list[int]:
    """The number of disclosure sets of each shape: C(6, e) · C(18 - 3e, g) · ways."""
    return [math.comb(NUM_E, e) * math.comb(NUM_E * PER_E - PER_E * e, g) * ways()[active_chains(e, g)][c]
            for e, g, c in SHAPES]


def signature_cut(seed: int = 0x6f74732e676f6c66) -> dict:
    """One uniformly random disclosure set of the family, sampled exactly: the shape by its share
    of the family, the revealed digests uniformly, the chain positions through the counting table."""
    import random
    rng = random.Random(seed)
    e, g, cost = rng.choices(SHAPES, weights=shape_weights())[0]
    revealed_e = set(rng.sample(range(NUM_E), e))
    open_e = set(range(NUM_E)) - revealed_e
    groups_under_open = [j for l in sorted(open_e) for j in range(PER_E * l, PER_E * l + PER_E)]
    revealed_g = set(rng.sample(groups_under_open, g))
    open_g = set(groups_under_open) - revealed_g
    chains = [k for j in sorted(open_g) for k in range(PER_G * j, PER_G * j + PER_G)]
    w, t_by_chain, budget = ways(), {}, cost
    for i, k in enumerate(chains):
        left = len(chains) - i
        r = rng.randrange(w[left][budget])
        c = 0
        while r >= w[left - 1][budget - c]:
            r -= w[left - 1][budget - c]
            c += 1
        t_by_chain[k] = LEN - c
        budget -= c
    total = 2 + len(open_e) + len(open_g) + sum(LEN - t for t in t_by_chain.values())
    assert budget == 0 and total == 103, (budget, total)
    assert len(revealed_e) + len(revealed_g) + len(t_by_chain) <= 42
    return {"open_e": open_e, "open_g": open_g, "revealed_e": revealed_e, "revealed_g": revealed_g,
            "t": t_by_chain}


# The lids: cubic curves between the corners (22, 284) and (838, 272). Only the control heights
# move in a blink; scheme-art.js mirrors these numbers.
LID_OPEN, LID_SHUT = (4, -4, 574, 578), (330, 326, 326, 330)
PUPIL = 46


def lid_paths(u1: float, u2: float, l1: float, l2: float) -> dict[str, str]:
    upper = f"M 22 284 C 180 {u1:g} 650 {u2:g} 838 272"
    lower = f"M 838 272 C 660 {l1:g} 200 {l2:g} 22 284"
    shut = 1 - (u1 - LID_SHUT[0]) / (LID_OPEN[0] - LID_SHUT[0])
    return {"aperture": f"{upper} {lower} Z", "upper": upper, "lower": lower,
            "lid-upper": f"{upper} C 650 {u2 - 12:g} 180 {u1 - 12:g} 22 284 Z",
            "lid-lower": f"{lower} C 200 {l2 + 5:g} 660 {l1 + 5:g} 838 272 Z",
            "crease": crease(shut)}


def crease(shut: float) -> str:
    """The fold above the upper lid: a thin crescent that sinks a little as the eye closes."""
    c = -23 + 34 * shut
    return f"M 118 216 C 250 {c:g} 610 {c - 6:g} 746 204 C 610 {c - 2.5:g} 250 {c + 3.5:g} 118 216 Z"


def iris_texture() -> tuple[str, str, str]:
    """Radial stroma fibres (a darker and a lighter set) and the wavy collarette, each one path."""
    import random
    rng = random.Random(0x6972)
    fibres = ["", ""]
    for layer, count in ((0, 150), (1, 110)):
        parts = []
        for i in range(count):
            a = 2 * math.pi * (i + rng.random()) / count
            r0, r1 = PUPIL + 3 + rng.random() * 10, 150 + rng.random() * 58
            bend = (rng.random() - 0.5) * 0.09
            (x0, y0), (x1, y1) = polar(r0, a), polar(r1, a + bend * 0.4)
            qx, qy = polar((r0 + r1) / 2, a + bend)
            parts.append(f"M{x0:.1f} {y0:.1f}Q{qx:.1f} {qy:.1f} {x1:.1f} {y1:.1f}")
        fibres[layer] = "".join(parts)
    pts = []
    for i in range(181):
        a = 2 * math.pi * i / 180
        r = 60 + 2.6 * math.sin(13 * a) + 1.3 * math.sin(29 * a + 1.3)
        x, y = polar(r, a)
        pts.append(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}")
    return fibres[0], fibres[1], "".join(pts) + "Z"


def stops(name: str, offsets: tuple[float, ...]) -> str:
    return "".join(f'<stop offset="{o:g}" class="{name}-{i}"/>' for i, o in enumerate(offsets))


@lru_cache(maxsize=1)
def svg() -> str:
    cut = signature_cut()
    shapes = ";".join(f"{e},{g},{c}" for e, g, c in SHAPES)
    lids = lid_paths(*LID_OPEN)
    dark_fibres, light_fibres, collarette = iris_texture()
    cx, cy = CX, CY
    out = [f'<svg viewBox="0 0 860 560" class="scheme-art" data-len="{LEN}" data-shapes="{shapes}" '
           f'data-eye="open" aria-hidden="true" focusable="false">',
           '<defs>',
           f'<clipPath id="mandala-eye-aperture"><path data-eye-aperture="" d="{lids["aperture"]}"/></clipPath>',
           f'<path id="art-upper" data-lid="upper" d="{lids["upper"]}"/>',
           f'<path id="art-lower" data-lid="lower" d="{lids["lower"]}"/>',
           # the eyeball: bright in the middle, shaded into the corners
           f'<radialGradient id="art-sclera" gradientUnits="userSpaceOnUse" cx="{cx}" cy="{cy + 10}" r="420" '
           f'gradientTransform="translate({cx} {cy}) scale(1 .62) translate({-cx} {-cy})">'
           + stops("sclera", (0, .4, .72, 1)) + '</radialGradient>',
           # a soft shadow ring around the limbus, where the iris sits in the eyeball
           f'<radialGradient id="art-limbus-shade" gradientUnits="userSpaceOnUse" cx="{cx}" cy="{cy}" r="236">'
           + stops("limbus", (.88, .905, 1)) + '</radialGradient>',
           f'<radialGradient id="art-iris" gradientUnits="userSpaceOnUse" cx="{cx}" cy="{cy}" r="214">'
           + stops("iris", (.2, .3, .42, .66, .86, .95, .985, 1)) + '</radialGradient>',
           # light through the cornea gathers on the far side of the iris from the light source
           f'<radialGradient id="art-caustic" gradientUnits="userSpaceOnUse" cx="{cx + 70}" cy="{cy + 80}" r="190">'
           + stops("caustic", (0, 1)) + '</radialGradient>',
           f'<radialGradient id="art-pupil" gradientUnits="userSpaceOnUse" cx="{cx}" cy="{cy}" r="{PUPIL + 4}">'
           + stops("pupil", (0, .78, .9, 1)) + '</radialGradient>',
           f'<radialGradient id="art-rim" gradientUnits="userSpaceOnUse" cx="{cx}" cy="{cy}" r="{PUPIL + 22}">'
           + stops("rim", (.5, .64, .7, .76, 1)) + '</radialGradient>',
           # the cornea's dome: a broad, faint sheen from the upper left
           f'<radialGradient id="art-gloss" gradientUnits="userSpaceOnUse" cx="{cx - 95}" cy="{cy - 105}" r="230">'
           + stops("gloss", (0, 1)) + '</radialGradient>',
           '<radialGradient id="art-spark">' + stops("spark", (0, .22, .5, 1)) + '</radialGradient>',
           '<radialGradient id="art-catch" cx=".42" cy=".38" r=".62">' + stops("catch", (0, .7, 1)) + '</radialGradient>',
           '</defs>',
           '<g class="eyeball" clip-path="url(#mandala-eye-aperture)">',
           '<rect class="sclera" x="0" y="0" width="860" height="560" fill="url(#art-sclera)"/>',
           f'<circle cx="{cx}" cy="{cy}" r="236" fill="url(#art-limbus-shade)"/>',
           f'<circle class="iris-boundary" cx="{cx}" cy="{cy}" r="214" fill="url(#art-iris)"/>',
           f'<path class="iris-fibre dark" d="{dark_fibres}"/>',
           f'<path class="iris-fibre light" d="{light_fibres}"/>',
           f'<circle cx="{cx}" cy="{cy}" r="212" fill="url(#art-caustic)"/>',
           f'<path class="collarette" d="{collarette}"/>']
    edges, nodes = [], []

    def status_chain(k: int, t: int) -> str:
        if k in cut["t"]:
            tk = cut["t"][k]
            return "revealed" if t == tk else ("recomputed" if t > tk else "untouched")
        return "untouched"

    for k in range(CHAINS):
        a = angle(k)
        j = k // PER_G
        g_open = j in cut["open_g"]
        # beads t = 14 (tip, nearest the group) .. 0 (source, outermost)
        pts = {t: polar(R_TIP + (LEN - t) * STEP, a) for t in range(LEN + 1)}
        for t in range(1, LEN + 1):
            (x1, y1), (x2, y2) = pts[t - 1], pts[t]
            st = "recomputed" if status_chain(k, t) == "recomputed" else "untouched"
            edges.append(f'<line class="e {st}" data-r="cedge" data-k="{k}" data-t="{t}" x1="{x1:.1f}" y1="{y1:.1f}" '
                         f'x2="{x2:.1f}" y2="{y2:.1f}"/>')
        for t in range(LEN + 1):
            x, y = pts[t]
            st = status_chain(k, t)
            if t == 0:
                s = 2.4
                nodes.append(f'<rect class="n src {st}" data-r="bead" data-k="{k}" data-t="{t}" data-x="{x:.1f}" '
                             f'data-y="{y:.1f}" x="{x - s:.1f}" y="{y - s:.1f}" width="{2 * s:.1f}" '
                             f'height="{2 * s:.1f}" transform="rotate(45 {x:.1f} {y:.1f})"/>')
            else:
                nodes.append(f'<circle class="n bead {st}" data-r="bead" data-k="{k}" data-t="{t}" cx="{x:.1f}" '
                             f'cy="{y:.1f}" r="1.85"/>')
        # tip -> group
        gx, gy = polar(R_G, angle(PER_G * j + 1))
        tx, ty = pts[LEN]
        st = "recomputed" if g_open else "untouched"
        edges.append(f'<line class="e {st}" data-r="tip" data-k="{k}" data-g="{j}" x1="{tx:.1f}" y1="{ty:.1f}" '
                     f'x2="{gx:.1f}" y2="{gy:.1f}"/>')
    for j in range(CHAINS // PER_G):
        l = j // PER_E
        gx, gy = polar(R_G, angle(PER_G * j + 1))
        ex, ey = polar(R_E, angle(PER_G * PER_E * l + 4))
        st = "revealed" if j in cut["revealed_g"] else ("recomputed" if j in cut["open_g"] else "untouched")
        est = "untouched" if l in cut["revealed_e"] else "recomputed"
        edges.append(f'<line class="e {est}" data-r="gedge" data-g="{j}" data-s="{l}" x1="{gx:.1f}" y1="{gy:.1f}" '
                     f'x2="{ex:.1f}" y2="{ey:.1f}"/>')
        nodes.append(f'<circle class="n g {st}" data-r="g" data-g="{j}" cx="{gx:.1f}" cy="{gy:.1f}" r="3"/>')
    for l in range(NUM_E):
        ex, ey = polar(R_E, angle(PER_G * PER_E * l + 4))
        st = "revealed" if l in cut["revealed_e"] else "recomputed"
        edges.append(f'<line class="e recomputed" data-r="redge" data-s="{l}" x1="{ex:.1f}" y1="{ey:.1f}" '
                     f'x2="{CX:.1f}" y2="{CY:.1f}"/>')
        nodes.append(f'<circle class="n e {st}" data-r="s" data-s="{l}" cx="{ex:.1f}" cy="{ey:.1f}" r="3.9"/>')
    out.extend(edges)
    out.extend(nodes)
    # the root is the pupil: dark, with a soft edge; its rim glows when the verifier reaches it
    out.extend([f'<circle class="root" data-root="" cx="{cx}" cy="{cy}" r="{PUPIL + 4}" fill="url(#art-pupil)"/>',
                f'<circle class="pupil-boundary" cx="{cx}" cy="{cy}" r="{PUPIL - .5}"/>',
                f'<circle class="root-glow" data-root-glow="" cx="{cx}" cy="{cy}" r="{PUPIL + 22}" '
                f'fill="url(#art-rim)" opacity="0"/>',
                '<g class="current" data-current=""></g>',
                # the lids shade the eyeball beneath them
                *(f'<use class="lid-shade" href="#art-upper" stroke-width="{96 - 9 * i}"/>' for i in range(10)),
                *(f'<use class="lid-shade" href="#art-lower" stroke-width="{36 - 7 * i}"/>' for i in range(4)),
                '<use class="waterline" href="#art-lower"/>',
                f'<circle cx="{cx}" cy="{cy}" r="214" fill="url(#art-gloss)"/>',
                f'<ellipse class="catchlight" cx="{cx - 36}" cy="{cy - 35}" rx="10.5" ry="8" fill="url(#art-catch)" '
                f'transform="rotate(-38 {cx - 36} {cy - 35})"/>',
                f'<circle class="catchlight-2" cx="{cx + 22}" cy="{cy + 25}" r="2.6"/>',
                '</g>',
                f'<path class="lid-crease" data-lid="crease" d="{lids["crease"]}"/>',
                f'<path class="lid lid-upper" data-lid="lid-upper" d="{lids["lid-upper"]}"/>',
                f'<path class="lid lid-lower" data-lid="lid-lower" d="{lids["lid-lower"]}"/>',
                '</svg>'])
    return "\n".join(out)
