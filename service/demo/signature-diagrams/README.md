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
