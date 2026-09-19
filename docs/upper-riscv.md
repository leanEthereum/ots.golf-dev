# RISC-V verification track

The second upper track scores a proved upper bound on the cycles of **every execution**,
accepting or rejecting, for every public key, message, signature, and oracle-answer path. Every
execution must terminate and agree with the specification.

## Certificate

[`OptimalOTS.Riscv.Submission`](../formal/OptimalOTS/Riscv.lean) contains the OTS specification,
a fixed assembly image, and an input-dependent fuel bound witnessing termination. A
`Submission.Certificate C` requires:

- Perfect correctness, deterministic verification, signing failure at most `2^-128`, public keys
  of 128 bits, messages of 256 bits, signatures of at most 5504 bits, key generation of at most
  1024 compressions and signing of at most `2^20` compressions.
- 127-bit strong security in the existing shared random-oracle experiment.
- Exact refinement of the Lean verifier by the machine's oracle computation, preserving
  queries. Faults and fuel exhaustion are excluded on every input; the machine is deterministic
  given the oracle's answers.
- At most `C` cycles on each execution, accepting or rejecting. The bound need not be attained.

Because refinement identifies the machine's oracle computation with the Lean verifier, the
admissibility and security proofs apply to the machine verifier. The security experiment counts
hash compressions for all parties; the score also counts the verifier's ordinary instructions.

## Machine and ABI

[`RiscvMachine.lean`](../formal/OptimalOTS/RiscvMachine.lean) uses the RV64IM subset provided by
[`riscv-zkvm` at `4634e41`](https://github.com/Verified-zkEVM/riscv-zkvm/tree/4634e41b229da4256e4a1f1688b94133fffa4af0).
Each ordinary instruction costs one cycle. Pseudo-instructions must be expanded.
The model fixes instruction costs rather than modeling a hardware pipeline.

`ECALL` selects one of two operations using `t0` (`x5`):

| `t0` | Operation | Arguments and result | Cycles |
|---:|---|---|---:|
| 0 | HALT | `a0` is 0 for rejection or 1 for acceptance | 1 |
| 1 | HASH | `a0`: input pointer; `a1`: bit length; `a2`: 8-byte-aligned pointer to a 32-byte buffer | `max(1, ceil(bits/512))` |

HASH uses the same bare oracle as key generation, signing and the attacker. Bits are read least
significant first within each byte. It reads the full input before writing the 256-bit answer;
buffers may overlap. Repeated queries are charged again. HASH has no extra one-cycle dispatch fee.
Other system calls, host accelerators and invalid memory accesses trap.

The loader packs raw inputs into memory, zeroes other memory and registers, installs the fixed
code and data, and sets these registers:

| Register | Initial value |
|---|---|
| `pc` | Code at `0x1000` |
| `sp` | `0x1000000` |
| `a0` | 128-bit public key at `0x400000` |
| `a1` | 256-bit message at `0x400010` |
| `a2` | Signature at `0x400030` |
| `a3` | Signature bit length, capped at 5505 |

The first 5504 signature bits are loaded; the length sentinel distinguishes oversized inputs.
A signature is the 128-bit nonce followed by the payload, so the payload starts at `0x400040`.
The image contains at most 262144 instructions and 1 MiB of fixed data, loaded at `0x200000`.
Code is immutable. Parsing, arithmetic, copying and comparison run inside the machine.

## Certified submission

The reference proof, a `UpperRiscv` submission root in the submissions repository, contains the
checked certificate
`OptimalOTS.Challenge.UpperRiscv.certificate : submission.Certificate 702`, exported from
`Solution.lean` with `claim.txt` at 702. It uses only `propext`, `Classical.choice` and
`Quot.sound`; no `native_decide`, `bv_decide` or added axiom appears anywhere in the root.

The OTS is a flat forest: 32 hash chains of length 15 under one root, with no group or subtree
digests. The index is the low 128 bits of `H(message ‖ nonce)`; it is **accepted** when its 32
nibbles sum to `target = 160`, every nibble value being allowed (`Valid.lean`). Chain `k` is
disclosed at position `15 - nibble k` (`FixedChoice.lean`), so every disclosure set is a cut of
the same cost, distinct indices give distinct cuts, and a signature is the nonce and 32 words,
4224 bits. The kernel checks that exactly

```
comp 32 160 = 44383521204130784290044027201113527 ≥ 2^115
```

indices are accepted (`Valid.card_validSet`), so signing succeeds within the `2^20` trials with
failure below `2^-128`.

The oracle has no labels, so the inputs separate the hash nodes. A chain input is the chain's
128-bit value above a 64-bit header: the address of the chain's slot in the machine and a level
tag, which the machine keeps in registers (`Constants.lean`). The root input is the 32 chain tops
with the headers between them, 6080 bits, exactly as the slots lie in memory. The three input
lengths (192, 6080 and the 384-bit index query) are distinct, so every query belongs to at most
one hash node. Key generation costs 492 compressions and verification 173. The security proof is
the forest proof of the compressions track, ported to this graph and to the header tags.

The implementation, `Program.lean`, has **1337 RV64IM instructions** and a 64-byte data image
holding four lane constants:

- **Index.** Save the public key in two registers, copy the nonce below the message so that
  `nonce ‖ message` is contiguous, hash it into the data area, and reject any length other than
  4224 bits. Eight lane words hold `8 · nibble` in 16-bit lanes (one shift and one mask each);
  their sum, multiplied by `0x0001000100010001`, has `8 · Σ nibbles` in its top lane, and the
  machine rejects unless it is `1280`. Each lane word is subtracted from a broadcast jump base
  and stored, giving every chain its jump target (`IndexPhase.lean`, `IndexArith.lean`).
- **Chains.** Chain `k`'s value lives at `slotAddr k`, 24 bytes after chain `k - 1`'s, after an
  8-byte header. Its block copies the disclosed word, writes the slot address as the header,
  loads its jump target and jumps into a table of 15 two-instruction steps: store the level tag
  in the header's top halfword, hash the 192-bit header and value in place (`ChainPhase.lean`).
  The last step's tag is zero, so after every chain the header is the root's.
- **Root.** The slots from chain 0 to chain 31 are the root input; its answer overwrites the last
  slot and its low 128 bits are compared with the saved key (`RootPhase.lean`).

Nodes are numbered chain-major, so the specification's sequential reader visits each chain's
nodes in the order the blocks run.

### Cycle accounting

Every ordinary instruction costs one cycle and every hash call `max(1, ⌈bits / 512⌉)`: one for the
index query and the chain steps, twelve for the root.

| Region | Instructions | Certified cycles |
|---|---:|---:|
| Index query, length check, lanes, sum check, level tags | 77 | 71 |
| 32 chain blocks: `9 + 2 · nibble` each | 1248 | 608 |
| Root input and 6080-bit hash | 4 | 15 |
| Decision | 8 | 8 |
| Total | 1337 | 702 |

The nibbles of an accepted index sum to 160, so the chains cost `32 · 9 + 2 · 160 = 608` cycles on
every accepted index (`ChainPhase.costFrom_zero`). Rejecting executions stop at one of the two
index checks or at the final decision, within the same bound.

### Proof structure

The certificate bundles four facts about `RiscvUpperForest.submission`: admissibility and
security (`Wire.admissible`, `Wire.secure`), and exact refinement with the cycle bound, both read
off `Verifier.image_refines`, which proves
`Riscv.Refines 1337 (initialState image pk m bits) (some <$> directVerify pk m bits) 702`.
`ForestVerifierProof.directVerify_eq` identifies the explicit interpreter with the certified
verifier. The refinement composes `IndexPhase.indexPhase_refines` (the query, the two rejections
and the context left for the chains), `ChainPhase.chainsFrom_refines` (by induction over the
chains; each chain is its prologue, `ChainBlock.prologue_refines`, and its steps from the disclosed
position, `ChainBlock.steps_refines`) and `RootPhase.rootDecision_refines`.

The official verifier accepts this root through the RISC-V challenge stub. Earlier images (the
1628-cycle forest with 63 chains, 21 groups and 7 subtrees, and before it 1632, 5513 and more
cycles) live in the git history.

## Attribution

The oracle syscall boundary and counted-execution approach were informed by
[Derek Sorensen's `xmss-verify-asm` at `003facc`](https://github.com/dhsorens/xmss-verify-asm/tree/003faccf2bb26f2b1a6945d4bf4b4792aae7395f).
That project proves an XMSS implementation correct for its own specification. Its benchmark's
OTS subtotal is not a universal cost theorem for this competition, and its 42 chain values plus
192-bit nonce exceed this competition's signature budget. We use the separately pinned machine
dependency and the ots.golf forest proof; no XMSS security or cost claim is imported here.
