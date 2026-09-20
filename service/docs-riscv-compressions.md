# Supplemental RISC-V compression bounds

`riscv-compression-bounds.json` is a maintainer-reviewed display catalog. An entry
adds a hashing bound and an immutable Lean source link to one verified RISC-V
submission. The cycle score, proof intake and record attribution are unchanged.
The catalog lives in the core checkout, so rebuilding the website restores it.

Before adding an entry, review the bound for every raw input and oracle path,
and establish that it concerns the exact `submission.scheme` implemented by the
machine certificate. Pin the submission ID, upstream repository, checked commit,
contract and cycle claim. A measured instruction profile is insufficient evidence.
Unlisted submissions show no supplemental bound.

For the 687-cycle submission, `Wire.lean:79` proves
`OptimalOTS.RiscvUpperForest.Wire.scheme.VerifyCostAtMost 170`.
`Candidate.lean` defines the machine submission using precisely `Wire.scheme`
and proves `submission_implements`. Its equality of oracle computations preserves
the complete hash queries and therefore their compression cost. These sources
are pinned to the original checked commit, not a moving branch.

This is a reviewed annotation of a source theorem, not a new result exported by
the hosted RISC-V comparator. Do not infer an exact maximum from an upper bound.
