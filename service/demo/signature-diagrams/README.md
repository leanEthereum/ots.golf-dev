# Signature diagram preview

Two explicitly selected fictional rows
display owner-drawn SVG images; all other rows display no diagram. The 702-cycle
example uses the same chain positions as the measured instruction profile. The
104-compression example uses the homepage forest's deterministic disclosure cut.
Two separate `/diagram-previews/` pages illustrate the public submissions in PRs
#6 (102 compressions) and #7 (100 compressions), with exact checked-source links.
They do not add submissions or verdicts to the local database.
Regenerate the images with `python3 generate.py` in this directory.

Each drawing includes its message encoding. The RISC-V drawing shows all 32
four-bit digits from the profiled input; digit `d` leaves `d` hashes to compute.
The three compression drawings show the index threshold and a fixed enumeration
of cuts. Their `setsName` uses noncomputable `family.equivFin`: we illustrate a
member of the allowed family, not an evaluated image of a claimed digest index.
The accessible descriptions identify those cuts as examples from the allowed family.

The original 104 construction uses 128 index bits and `2^115` accepted indices.
PR #6 uses 128 bits and `45 * 2^109`; PR #7 uses 127 bits and `45 * 2^108`.
Both public schemes have 54 chains of 18 steps, 18 ternary group hashes, and one
root. Six group digests plus 36 chain values are revealed. The remaining chain
hashes sum to 84 for #6 and 82 for #7; add 12 group hashes, five root compressions,
and one index compression. The generator asserts these constraints.

The rendering has no tree-specific schema: any SVG drawing can replace an image.
It uses an image element, not inline arbitrary SVG markup. On narrow screens the
image scrolls horizontally within its own frame.

## Owner workflow

Production diagrams come from the submissions repository, separately from these fixtures.
See [the owner guide](../../../tools/submissions_template/SIGNATURE_DIAGRAMS.md).
The website fetches the registry and images from one immutable revision of main; local
fixtures and `/diagram-previews/` routes are available only in development with `OTS_PHONY=1`.

## 92-compression preview (PR #8)

The new local preview preserves saucegodbased's original record identity. Its forest
has 54 chains of 18 steps and uses 129-bit values, unlike the earlier 128-bit diagrams.
The highlighted cut has six disclosed group values and 36 chain disclosures with
74 remaining chain hashes. Add 12 group hashes, five root compressions and the
message/nonce hash for 92. The message is 256 bits and the nonce 86 bits.

The encoding accepts the low 129 digest bits below `45 * 2^110`. Fixed finite
equivalences map those accepted indices to aliases, to classes in 72 tiers, and
then to distinct disclosure cuts. A class in tier j has `2^(j+1)` aliases. The signer
draws all `2^20` nonces independently with replacement and keeps the first occurrence
in the lowest accepted tier. It does not stop at the first accepted nonce.

The illustrative cut satisfies `WideForest.shapes` (six groups, chain rank 74).
We do not evaluate the noncomputable `family.equivFin` or claim this drawing is
the decoder output of a particular digest, or identify its tier in the selected
class embedding. The generator checks the structural and compression counts.
These definitions are in the original checked PR #8 source, `ProofBundle03.lean`
(`WideNames`, `WideCuts`, `WeightedSchedule`, `WideScheme`) and `ProofBundle02.lean`
(`WeightedScheme.Signing`). No proof source or verdict is changed.
