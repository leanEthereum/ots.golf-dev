"""Reproduce the owner drawings and the local 92-compression preview.

The website only consumes SVG images; other owner drawings need not use this
generator or follow either of these graph shapes.
"""
from pathlib import Path
import json
import sys
import random
from html import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.scheme_art import signature_cut

HERE = Path(__file__).resolve().parent
# Nibbles from the same accepting input as the approved 702-cycle profile.
DIGITS = [6, 2, 2, 2, 1, 2, 13, 1, 1, 10, 12, 3, 8, 3, 2, 9,
          0, 9, 1, 2, 4, 11, 8, 2, 9, 3, 9, 14, 2, 6, 0, 3]
assert len(DIGITS) == 32 and sum(DIGITS) == 160


class Drawing:
    def __init__(self, title, description, *, bits=128, threshold=None, selection=None, weighted=False):
        self.weighted = weighted
        height = 680 if weighted else 640
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 {height}" role="img">',
                      f'<title>{escape(title)}</title><desc>{escape(description)}</desc>',
                      '<style>text{font-family:system-ui,sans-serif;font-size:12px;fill:#6f6d67}'
                      '.heading{font-size:13px;font-weight:600;fill:#52514e}'
                      '.edge{fill:none;stroke:#dededa;stroke-width:1.15}'
                      '.edge.active{stroke:#2a78d6;stroke-width:1.5}'
                      '.node{fill:#fcfcfb;stroke:#d2d2cb;stroke-width:1.15}'
                      '.node.active{stroke:#2a78d6;stroke-width:1.5}'
                      '.node.revealed{fill:#2a78d6;stroke:#fcfcfb;stroke-width:1.4}'
                      '</style>', f'<rect width="760" height="{height}" fill="#fcfcfb"/>']
        self.text(28, 32, title, css="heading")
        self.text(732, 32, 'Hash direction ↓', anchor='end')
        cards = [(28, 180, 'Message + nonce', '384-bit input'),
                 (238, 210, 'HASH → integer i', f'Low {bits} bits of the digest'),
                 (478, 254, 'Fixed enumeration of cuts' if threshold else 'Split into 32 four-bit digits',
                  'One index selects a whole pattern' if threshold else '0110 | 0010 | 0010 | …')]
        if weighted:
            cards = [(28, 180, 'Message + nonce', 'Try different nonces'),
                     (238, 210, 'HASH → candidate pattern', 'Which forest values to reveal'),
                     (478, 254, 'Non-uniform selection', 'Prefer harder-to-hit patterns')]
        for x, width, heading, note in cards:
            self.parts.append(f'<rect x="{x}" y="53" width="{width}" height="52" rx="7" fill="#f5f5f2" stroke="#e6e5e1"/>')
            self.text(x + width/2, 74, heading, anchor='middle', css='heading')
            self.text(x + width/2, 93, note, anchor='middle')
        self.text(223, 84, '→', anchor='middle')
        self.text(463, 84, '→', anchor='middle')
        if weighted:
            self.text(380, 132, 'Rare means unlikely under a single fresh hash.', anchor='middle')
            self.text(380, 156, 'The signer tries many nonces, then keeps the rarest valid pattern found.', anchor='middle')
            self.text(380, 180, 'Every selected pattern still has the same 92-compression verification cost.', anchor='middle')
        elif threshold:
            self.text(380, 129, f'Accept i < {threshold}; otherwise try a new nonce.', anchor='middle')
            if selection:
                self.text(380, 153, selection, anchor='middle', css='heading')
        else:
            self.text(380, 129, 'Accept when the digits sum to 160; otherwise try a new nonce.', anchor='middle')
            self.text(380, 151, 'Each digit is the number of hashes remaining on its chain.', anchor='middle')
            for k, digit in enumerate(DIGITS):
                self.text(70 + 20*k, 178, str(digit), anchor='middle', css='heading')
        divider, shift = 196, 160
        self.parts.append(f'<path d="M28 {divider} H732" stroke="#e6e5e1"/><g transform="translate(0 {shift})">')

    def text(self, x, y, value, anchor='start', css=''):
        self.parts.append(f'<text x="{x:g}" y="{y:g}" text-anchor="{anchor}" class="{css}">{escape(value)}</text>')

    def edge(self, x, y, xx, yy, active=False):
        self.parts.append(f'<path class="edge{" active" if active else ""}" d="M{x:g} {y:g} L{xx:g} {yy:g}"/>')

    def node(self, x, y, state, radius=2.6):
        if state == 'revealed':
            radius = 4.8
        self.parts.append(f'<circle class="node {state}" cx="{x:g}" cy="{y:g}" r="{radius:g}"/>')

    def root(self, y):
        self.parts.append(f'<rect x="323" y="{y}" width="114" height="30" rx="15" fill="#e5effc" stroke="#2a78d6"/>')
        self.text(380, y + 20, 'Public key', anchor='middle', css='heading')

    def write(self, name):
        if self.weighted:
            self.text(380, 444, '74 chain + 12 group + 5 root + 1 index = 92 compressions',
                      anchor='middle', css='heading')
        offset = 40 if self.weighted else 0
        self.parts.append(f'<path d="M28 {432 + offset} H732" stroke="#e6e5e1"/>')
        for x, state, label in [(34, 'revealed', 'Revealed in signature'),
                                (275, 'active', 'Computed by verifier'),
                                (513, '', 'Unused in verification')]:
            self.node(x, 454 + offset, state, 3.4)
            self.text(x + 12, 458 + offset, label)
        (HERE / name).write_text('\n'.join(self.parts + ['</g></svg>']) + '\n')


flat_alt = ('32 parallel chains, each with 15 hash steps. Blue filled dots mark the 32 values '
            'revealed in one signature. Blue paths hash them forward to the chain endpoints, '
            'which are used to reconstruct the public key. '
            'Grey nodes are unused during verification of this signature. '
            'The low 128 digest bits split into 32 four-bit digits; signing tries nonces '
            'until their sum is 160. Each digit gives the remaining hash steps for its chain.')
d = Drawing('32 hash chains · 15 steps each', flat_alt)
xs = [70 + 20 * k for k in range(32)]
ys = [70 + 15 * t for t in range(16)]
for k, x in enumerate(xs):
    reveal = 15 - DIGITS[k]
    for t in range(15):
        d.edge(x, ys[t], x, ys[t + 1], t >= reveal)
    d.edge(x, ys[-1], x, 325, True)
    for t, y in enumerate(ys):
        d.node(x, y, 'revealed' if t == reveal else 'active' if t > reveal else '')
d.edge(xs[0], 325, xs[-1], 325, True)
d.edge(380, 325, 380, 373, True)
d.root(373)
d.write('flat-chains.svg')

forest_alt = ('A forest of 54 chains with 14 hash steps each. Groups of three chain endpoints '
              'are hashed into 18 group digests; groups of three digests into six subtree digests; '
              'these form the public key. A sample disclosure cut is highlighted: blue filled '
              'dots are revealed values, blue outlined nodes are recomputed, and grey branches '
              'are unused for this cut. The low 128 digest bits select an index below 2^115 '
              'in a fixed enumeration of disclosure cuts, each revealing at most 42 values. '
              'The drawn cut illustrates this family without claiming a particular digest index.')
d = Drawing('54 hash chains · 14 steps each', forest_alt, threshold='2¹¹⁵',
            selection='Choose subtree values, group values and chain positions · at most 42 values')
cut = signature_cut()
xs = [62 + 12 * k for k in range(54)]
ys = [64 + 13 * t for t in range(15)]
gx = [sum(xs[3*j:3*j+3]) / 3 for j in range(18)]
ex = [sum(gx[3*j:3*j+3]) / 3 for j in range(6)]
gy, ey, ry = 285, 331, 388
for k, x in enumerate(xs):
    revealed = cut['t'].get(k)
    for t in range(14):
        d.edge(x, ys[t], x, ys[t+1], revealed is not None and t >= revealed)
    d.edge(x, ys[-1], gx[k//3], gy, revealed is not None)
for j, x in enumerate(gx):
    d.edge(x, gy, ex[j//3], ey, j//3 in cut['open_e'])
for e, x in enumerate(ex):
    d.edge(x, ey, 380, ry, True)
for k, x in enumerate(xs):
    revealed = cut['t'].get(k)
    for t, y in enumerate(ys):
        state = 'revealed' if t == revealed else 'active' if revealed is not None and t > revealed else ''
        d.node(x, y, state, 2)
for j, x in enumerate(gx):
    d.node(x, gy, 'revealed' if j in cut['revealed_g'] else 'active' if j in cut['open_g'] else '', 3.2)
for e, x in enumerate(ex):
    d.node(x, ey, 'revealed' if e in cut['revealed_e'] else 'active', 3.8)
d.root(ry - 4)
d.write('forest.svg')


def shallow(claim):
    """PRs #6, #7 and #8 share the forest shape, with different indexed cut families.

    ShallowNames: 54 chains × 18 steps -> 18 ternary groups -> root.
    ShallowCuts: six revealed groups, 36 chain disclosures, cost 84, 82 or 74; #8 also uses 129-bit values and weighted aliases.
    We illustrate a family member, not an evaluated noncomputable setsName index.
    """
    chain_cost = claim - 18  # 12 group hashes + 5 root compressions + 1 index
    assert chain_cost in (74, 82, 84)
    rng = random.Random(20260920)
    revealed_groups = set(rng.sample(range(18), 6))
    active = [k for k in range(54) if k // 3 not in revealed_groups]
    # Uniform bounded composition, matching the cost constraint in ShallowCuts.
    ways = [[0] * (chain_cost + 1) for _ in range(37)]
    ways[0][0] = 1
    for n in range(1, 37):
        for s in range(chain_cost + 1):
            ways[n][s] = sum(ways[n-1][s-c] for c in range(min(18, s) + 1))
    positions, budget = {}, chain_cost
    for i, k in enumerate(active):
        left = len(active) - i - 1
        pick = rng.randrange(ways[left+1][budget])
        cost = 0
        while pick >= ways[left][budget-cost]:
            pick -= ways[left][budget-cost]
            cost += 1
        positions[k] = 18 - cost
        budget -= cost
    assert budget == 0 and len(positions) + len(revealed_groups) == 42
    assert sum(18 - p for p in positions.values()) + 12 + 5 + 1 == claim
    bits, threshold = (128, '45 × 2¹⁰⁹') if claim == 102 else (127, '45 × 2¹⁰⁸')
    alt = (f'54 chains of 18 steps feed 18 ternary group hashes and then the public key. '
           f'The low {bits} digest bits select a whole disclosure pattern through a fixed '
           f'enumeration, accepting indices below {threshold}. Signing retries the nonce '
           f'otherwise. Each cut reveals six group values and 36 chain values with '
           f'{chain_cost} chain hashes remaining. The drawing illustrates an allowed cut, '
           f'without claiming a particular digest index. Blue dots are revealed values, '
           f'blue paths are recomputed, and grey branches are unused for this cut.')
    if claim == 92:
        bits, threshold = 129, '45 × 2¹¹⁰'
        alt = ('54 tagged chains of 18 steps, with 129-bit values, feed 18 ternary group hashes '
               'and the public key. The low 129 bits of HASH(message || 86-bit nonce) are '
               'accepted below 45 × 2^110, then mapped through a fixed alias enumeration to '
               'a tier and a cut. There are 72 tiers; tier j gives each cut 2^(j+1) digest '
               'aliases. Signing draws all 2^20 nonces independently with replacement and '
               'keeps the first occurrence in the lowest accepted tier, failing if none is '
               'accepted. Verification uses only the chosen nonce and disclosure pattern. '
               'The drawn cut illustrates the structural family; it is not an evaluated '
               'decoder output or a claimed member of the selected class embedding. '
               'Six group values and 36 chain values are revealed. Blue paths compute '
               '74 chain hashes, 12 group hashes and five root compressions; with the index '
               'hash, the total is 92. Grey branches are unused by the verifier.')
    title = '54 chains · 18 steps · 129-bit values' if claim == 92 else '54 hash chains · 18 steps each'
    d = Drawing(title, alt, bits=bits, threshold=threshold, weighted=claim == 92)
    xs = [62 + 12 * k for k in range(54)]
    ys = [64 + 12 * t for t in range(19)]
    gx = [sum(xs[3*j:3*j+3]) / 3 for j in range(18)]
    gy, ry = 324, 384
    for k, x in enumerate(xs):
        p = positions.get(k)
        for t in range(18):
            d.edge(x, ys[t], x, ys[t+1], p is not None and t >= p)
        d.edge(x, ys[-1], gx[k//3], gy, p is not None)
    for x in gx:
        d.edge(x, gy, 380, ry, True)
    for k, x in enumerate(xs):
        p = positions.get(k)
        for t, y in enumerate(ys):
            state = 'revealed' if t == p else 'active' if p is not None and t > p else ''
            d.node(x, y, state, 2)
    for j, x in enumerate(gx):
        d.node(x, gy, 'revealed' if j in revealed_groups else 'active', 3.2)
    d.root(ry)
    d.write(f'shallow-{claim}.svg')
    return alt


public = {}
for claim, sid, commit, pr in [
    (92, '4abfb06a48549d67349e07c50b4dc5ca', '7be6d31b9de82713e5b088f17e62e30a9198a734', 8),
    (102, '440fbe4103a5cfff1f213e25ac09bfd9', 'ceeb8503c3950869440af1cb6fa69b52b79044fc', 6),
    (100, 'ad5f125ca8ee77f306dc5fa1f0854ed9', '2dfaf14e5a570c1ceb9637a55d4b60dcc65c3a13', 7),
]:
    public[sid] = {'claim': claim, 'commit': commit, 'pr': pr, 'login': 'saucegodbased',
                   'image': f'shallow-{claim}.svg', 'alt': shallow(claim)}
    if claim == 92:
        public[sid]['intuition'] = (
            'The signer tries 2²⁰ nonces and keeps the rarest valid pattern found: one that '
            'a single fresh hash is unlikely to hit, making it a harder target for a forger. '
            'Spending more effort on this search allows a smaller family of patterns and '
            'cheaper verification.')
(HERE / 'public-previews.json').write_text(json.dumps(public, indent=2) + '\n')

(HERE / 'index.json').write_text(json.dumps({'version': 1, 'diagrams': {
    'upper-riscv-satoshi-nakamoto-2': {
        'track': 'upper-riscv', 'image': 'flat-chains.svg', 'alt': flat_alt,
    },
    'upper-compressions-satoshi-nakamoto-6': {
        'track': 'upper-compressions', 'image': 'forest.svg', 'alt': forest_alt,
    },
}}, indent=2) + '\n')
