import OptimalOTS.Model
import LeanerVM.Semantics.Execution

/-!
# The competition's leanISA machine

leanISA is the six-instruction ISA of leanVM-b. Its semantics are the pinned `leanerVM`
formalisation; this file changes exactly two things and states them precisely.

**Memory is committed, not written.** A leanISA program does not compute: it *checks*. The
prover commits a whole memory image `MemImage κ = Fin (2 ^ κ) → E` of `2 ^ κ` 192-bit words
before execution, at a log-size `κ` it chooses in `[16, 32]`, and every instruction reads the
cells it names and asserts a relation on them. A violated assertion is not a rejection: it means
this execution does not exist. So the machine has no accept/reject output. **Acceptance is the
existence of a committed image that drives the run to the sentinel counter**, and rejection is
the absence of one. That is why `LeanIsa.lean` needs both a soundness and a faithfulness clause
where `Riscv.lean` needs one equation.

**`BLAKE2S` is the competition's random oracle.** `leanerVM`'s `BLAKE2S` is the concrete RFC 7693
compression. That cannot be used here, because the competition's security statements are
random-oracle statements. The arm below instead queries the one shared oracle of `Model.lean` on
the exact 896 bits the instruction consumes — the chaining pair, the four message cells and the
metadata cell — and asserts the committed output pair against the 256-bit answer. Everything
else about the instruction, including the canonicality of all nine cells, is unchanged.

**The public boundary is idealised, and the idealisation is priced.** leanVM's public input is
256 bits, far less than this competition's 6016-bit statement, so a real program would bind the
statement by re-deriving a digest of it — twelve `BLAKE2S`. Making the loader do that turns
soundness into a cryptographic statement and `Submission.Sound` unsatisfiable, so the loader
pins the statement directly and `Submission.CyclesAtMost` adds `boundaryCycles` to every claim
instead. Section 7 gives the argument in full.

The other five instructions are not re-specified here. `execute` calls
`LeanerVM.Semantics.execute` on them, so they cannot drift from the pinned formalisation.

Each executed instruction costs one cycle, as each ordinary RISC-V instruction does in
`RiscvMachine.lean`, except `BLAKE2S`, which costs ten.
-/

namespace OptimalOTS.LeanIsa

open LeanerVM.Parameters LeanerVM.Semantics OracleComp

/-! ## 1. The cost of an instruction -/

/-- Cycles charged for one executed instruction. Five of the six cost one, like an ordinary
RISC-V instruction.

`BLAKE2S` costs ten. That multiplier is a competition parameter, not a measurement, and the
score is exactly `#instructions + 9 · #BLAKE2S`, so it is worth stating what it is not. Two
other numbers were available and rejected. Counting bus flushes and constraints from §5.1 and
§7 of the specification — two for the state, two for the bytecode read, two per memory read,
plus constraints — gives 10/10/6/10/12 for the five cheap opcodes and 22 for `BLAKE2S`; that
prices the row's bus traffic but not the Flock BLAKE2s R1CS over a Boolean witness, which
dominates it. Charging `blockCost` of the 896-bit query, as `Riscv` charges `HASH`, gives 2,
which prices the message bits and nothing else. Ten is the maintainers' standing choice pending
a measured Flock cost; repricing it is the same open question as `NEXT_COMPTETION.md`'s
"RiscV: 4 cycles instead of 1 for every hash compression", and is a one-constant change here. -/
def weight : Opcode → ℕ
  | .xor => 1
  | .mulNative => 1
  | .setConstant => 1
  | .deref => 1
  | .jump => 1
  | .blake2s => 10

/-! ## 2. Cells and bit strings

A memory word is an element of `E = K[y]/(y³ + y + 1)`, three 64-bit limbs. A *canonical* cell
(`IsCanonical128`) has a zero top limb and so holds 128 bits, the pair of limbs `a₀ + a₁·y`.
`BLAKE2S` operates only on canonical cells. -/

/-- The 128 bits of a cell: limb 0 in the low half, limb 1 in the high half. The top limb is
ignored, as it is by `LeanerVM.Semantics.cellWords`. -/
def cellBits (x : E) : BitVec 128 := x.limb 1 ++ x.limb 0

/-- The canonical cell holding 128 given bits. Inverse to `cellBits` on canonical cells. -/
def cellOfBits (b : BitVec 128) : E := E.ofLimbs (b.extractLsb' 0 64) (b.extractLsb' 64 64) 0

/-- Reading 128 bits into a cell and back is the identity. -/
theorem cellBits_cellOfBits (b : BitVec 128) : cellBits (cellOfBits b) = b := by
  simp [cellBits, cellOfBits,
    BitVec.extractLsb'_append_extractLsb'_eq_extractLsb' (start₁ := 0) (len₁ := 64) rfl]

/-- Canonical cells with the same 128 bits are the same cell. This is what ties the last
absorption step's output cells to the boundary cells the loader pinned. -/
theorem eq_of_cellBits_eq {x z : E} (hx : IsCanonical128 x) (hz : IsCanonical128 z)
    (h : cellBits x = cellBits z) : x = z := by
  -- The core split lemmas are stated at `BitVec (w + w')`. Reading the halves back out of
  -- `cellBits x : BitVec 128` directly would ask the unifier to solve `128 =?= ?w + ?w'` with
  -- both widths open, so the split is done on `BitVec 64` halves, where the width of the
  -- append is the literal `64 + 64`.
  have split : ∀ a b c d : BitVec 64, a ++ b = c ++ d → a = c ∧ b = d := by
    intro a b c d hab
    refine ⟨?_, ?_⟩
    · have := congrArg (BitVec.extractLsb' 64 64) hab
      rwa [BitVec.extractLsb'_append_eq_left, BitVec.extractLsb'_append_eq_left] at this
    · have := congrArg (BitVec.extractLsb' 0 64) hab
      rwa [BitVec.extractLsb'_append_eq_right, BitVec.extractLsb'_append_eq_right] at this
  obtain ⟨h1, h0⟩ := split _ _ _ _ h
  have hx2 : x.limb 2 = 0 := hx
  have hz2 : z.limb 2 = 0 := hz
  apply E.ext; intro i
  fin_cases i <;> simp [h0, h1, hx2, hz2]

/-! ## 3. `BLAKE2S` as an oracle query -/

/-- The oracle input of one compression: the 256-bit chaining value, the 512-bit message block,
then the 128-bit metadata, least significant bit first — 896 bits. The metadata carries the
64-bit counter and the two finalisation flag words, so it is part of what determines the answer.

This is the machine's only hash interface. A program binding the statement to leanVM's real
256-bit public input would fold it over `statementBlocks` blocks, one `BLAKE2S` each; section 7
explains why the loader idealises that away and `boundaryCycles` charges for it. -/
def hashInput (cv : BitVec 256) (block : BitVec 512) (md : BitVec 128) : BitVec 896 :=
  ofBits 896 (toBits cv ++ toBits block ++ toBits md)

/-- The oracle input of one `BLAKE2S` instruction, read off its nine cells: the chaining pair
`cv₀, cv₁` low first, the four message cells in operand order, then the metadata cell. -/
def blake2sQuery (m : Fin 4 → E) (cv0 cv1 md : E) : BitVec 896 :=
  hashInput (cellBits cv1 ++ cellBits cv0)
    (cellBits (m 3) ++ cellBits (m 2) ++ cellBits (m 1) ++ cellBits (m 0))
    (cellBits md)

/-- The `BLAKE2S` relation under the competition oracle. This is
`LeanerVM.Semantics.CompressCells` with its concrete compression replaced by the oracle's
answer: the same six canonicality conditions on the nine cells, and the committed output pair
holding the 256-bit answer, low half in `out0`. -/
def OracleCompressCells (m : Fin 4 → E) (cv0 cv1 out0 out1 md : E)
    (answer : BitVec hashBits) : Prop :=
  (∀ i, IsCanonical128 (m i)) ∧ IsCanonical128 cv0 ∧ IsCanonical128 cv1 ∧
    IsCanonical128 out0 ∧ IsCanonical128 out1 ∧ IsCanonical128 md ∧
    cellBits out0 = answer.extractLsb' 0 128 ∧
    cellBits out1 = answer.extractLsb' 128 128

instance {m : Fin 4 → E} {cv0 cv1 out0 out1 md : E} {answer : BitVec hashBits} :
    Decidable (OracleCompressCells m cv0 cv1 out0 out1 md answer) := by
  unfold OracleCompressCells; infer_instance

/-! ## 4. One instruction -/

/-- Execute one instruction from registers `r` over the committed image `L`.

On `XOR`, `MUL_NATIVE`, `SET_CONSTANT`, `DEREF` and `JUMP` this *is*
`LeanerVM.Semantics.execute`, so those five arms cannot drift from the pinned specification.
`BLAKE2S` reads the same nine cells in the same order, queries the oracle on `blake2sQuery`, and
asserts `OracleCompressCells`.

`none` is a failed read, a failed fetch or a false relation. In this model that is not a
rejection: it means the committed image does not drive an execution through this instruction. -/
noncomputable def execute {κ : ℕ} (L : MemImage κ) (r : Regs K) :
    Instr → OracleComp Spec (Option (Regs K))
  | .blake2s om ocv oout omd =>
    match (do
      let m0 ← L.read (r.fp * om 0)
      let m1 ← L.read (r.fp * om 1)
      let m2 ← L.read (r.fp * om 2)
      let m3 ← L.read (r.fp * om 3)
      let cv0 ← L.read (r.fp * ocv)
      let cv1 ← L.read (r.fp * (g * ocv))
      let out0 ← L.read (r.fp * oout)
      let out1 ← L.read (r.fp * (g * oout))
      let md ← L.read (r.fp * omd)
      pure ((![m0, m1, m2, m3] : Fin 4 → E), cv0, cv1, out0, out1, md)) with
    | none => pure none
    | some (m, cv0, cv1, out0, out1, md) => do
      let answer ← hash (blake2sQuery m cv0 cv1 md)
      pure (if OracleCompressCells m cv0 cv1 out0 out1 md answer then some r.next else none)
  | i => pure (LeanerVM.Semantics.execute L r i)

/-- Away from `BLAKE2S`, this machine *is* `leanerVM`'s. The catch-all arm makes this true by
definition rather than by transcription, so the five instructions cannot drift from the pin; the
theorem records the fact for readers and breaks if the arm is ever specialised. -/
theorem execute_eq_leanerVM {κ : ℕ} (L : MemImage κ) (r : Regs K) (i : Instr)
    (h : i.opcode ≠ .blake2s) : execute L r i = pure (LeanerVM.Semantics.execute L r i) := by
  cases i <;> first | rfl | exact absurd rfl h

/-! ## 5. The loop and its cost -/

/-- Run exactly `n` instructions from `r`, accumulating weighted cycles.

`some cost` when all `n` steps validate, none of the `n` states stepped from sits at the
sentinel counter, and the state after them is `Regs.final` — that is, exactly when
`LeanerVM.Semantics.run` reports a valid execution of `n` steps, with `BLAKE2S` read through the
oracle. `none` otherwise. `cost` is the sum of `weight` over the instructions executed. -/
noncomputable def runCost (prog : Program) {κ : ℕ} (L : MemImage κ) :
    ℕ → Regs K → OracleComp Spec (Option ℕ)
  | 0, r => pure (if r.pc = prog.finalPc ∧ r.fp = 1 then some 0 else none)
  | n + 1, r =>
    if r.pc = prog.finalPc then pure none else
    match prog.fetch r.pc with
    | none => pure none
    | some ins => do
      match ← execute L r ins with
      | none => pure none
      | some next => Option.map (weight ins.opcode + ·) <$> runCost prog L n next

/-! ## 6. Well-formed bytecode -/

/-- The greatest admitted bytecode log-size, `2 ^ 18 = 262144` instructions: the same
*instruction count* `Riscv.Image.Valid` admits.

The budgets are not otherwise equal, and the difference favours leanISA. `Riscv.Image.Valid`
also caps `data.length ≤ 1048576`, so a RISC-V image carries about 2 MiB of free constants
between its 32-bit instructions and its 1 MiB data section. A leanISA slot carries a 192-bit
immediate (`Instr.setConstant (o : K) (k : E)`), so `2 ^ 18` slots carry about 6 MiB. Matching
instruction counts is the right parity for a cycle competition, but a reader should not read
the cap as equal expressive budget.

This cap is load-bearing, not hygiene. `LeanerVM.Semantics.Program.code` is a *function*
`Fin (2 ^ κ_bc) → Instr`, not a finite list, and `κ_bc ≤ 32` alone would let a submission commit
a four-billion-slot bytecode for free. leanISA can then read such a table in constant time — a
`JUMP` lands at a prover-chosen slot, a `DEREF` in `pc` mode ties the landing slot to a value
derived from the input, and a `SET_CONSTANT` there yields the entry. Every non-hash part of a
verifier (digit extraction, checksum, chain-length selection) could be tabulated and read for a
handful of cycles, so the score would stop measuring anything but the hashes. -/
def maxProgramLogSize : ℕ := 18

/-- The greatest number of table rows a submission may require the prover to seed and finalize:
one row per bytecode slot and one per memory cell, `2 ^ 20 = 1048576` of them together.

This bounds a cost the cycle score is blind to. Sections 5.1 and 7 charge two bus flushes per
row in the seed phase and two in the finalize phase, over **all** `2 ^ κ_bc` bytecode slots and
**all** `2 ^ κ_mem` memory cells, whether or not the execution touches them. No per-opcode
weight can see that, so without a cap a submission could announce `κ_mem = 32` — four billion
cells, eight billion flushes — and still show a three-digit cycle score.

The number is deliberately the one `Riscv.Image.byteSize` is capped at, and it is generous: the
loader pins 47 cells, an OTS verifier's hint space is thousands more, and `minLogMem` already
grants 65536. In practice it admits the full `2 ^ 18` bytecode together with `κ_mem ≤ 19`,
eight times the minimum. A submission that genuinely needs more is a reason to revisit this
constant, exactly as the RISC-V image budget was revisited.

What a cap cannot do is make seeding cheap. At the *minimum* memory size the seed and finalize
phases already flush `2 · (2 ^ 16 + 2 ^ κ_bc)` times, which dwarfs a three-digit cycle score at
roughly ten flushes per cycle. The cycle score is the cost of the *execution*, not of the
instance; this constant stops the part it cannot see from growing without bound. -/
def maxSeededRows : ℕ := 1048576

/-- The index of the last bytecode slot, `2 ^ κ_bc − 1`; its address is `Program.finalPc`. -/
def sentinelSlot (prog : Program) : Fin (2 ^ prog.logSize) :=
  ⟨2 ^ prog.logSize - 1, by have := Nat.one_le_two_pow (n := prog.logSize); omega⟩

/-- Well-formed bytecode: it fits the instruction budget, and the halt slot holds no `JUMP`.

The size cap is what stops the free lookup table described at `maxProgramLogSize`.

The halt-slot condition is a forward-compatibility hook, not a live obligation. It constrains
nothing that `runCost` can do: `run` tests the counter before
each fetch, so the last slot never executes, and a submitter satisfies the clause by putting an
`XOR` there. It is carried because the arithmetization is looser than `run` — a bus-balanced
assignment may contain closed walks (§6.1, Proposition 6.1), and a row at the halt address would
be one, with `JUMP` the only instruction able to move `pc` anywhere but `g · pc`. The theorem
that would consume this hypothesis does not exist yet: `WellFormedBytecode`,
`no_row_at_sentinel` and `exists_run_of_balanced` appear in `leanerVM` only inside the
doc-comment of `LeanerVM.Arithmetization.Statement`'s blocked Layer 9. Until that lands, the
gap between `run` and a balanced bus is a stated boundary of this track. -/
def BytecodeValid (prog : Program) : Prop :=
  prog.logSize ≤ maxProgramLogSize ∧ (prog.code (sentinelSlot prog)).opcode ≠ .jump

instance (prog : Program) : Decidable (BytecodeValid prog) := by
  unfold BytecodeValid; infer_instance

/-! ## 7. The loader and the public-boundary surcharge

leanVM pins exactly **two** memory cells: its public input is 256 bits (specification §2;
`LeanerVM.Semantics.HasPublicBoundary`). A real leanISA verifier of this competition's inputs
therefore cannot be handed the public key, message and signature as trusted memory. It receives
a digest of them and must re-derive that digest from prover-committed cells, one `BLAKE2S` per
512-bit block, before it may trust a single bit.

This contract idealises that boundary. The loader pins the statement into the lowest
`inputCells` cells, as `Riscv.initialState` writes the raw input into machine memory, and
everything above them stays the prover's.

The reason is not convenience. Routing the statement through a 256-bit digest makes soundness a
*cryptographic* statement: two statements collide under some oracle assignment, the machine
cannot tell them apart because the digest is all it sees, and so "the machine never completes on
a rejected input" is false on that assignment. `Submission.Sound` is a `probTrue … = 0`, which
quantifies over every assignment rather than over probability, so it would become unsatisfiable
for every program. Idealising the boundary keeps soundness finite and discharge-able.

The cost of the idealisation is priced rather than hidden: `Submission.CyclesAtMost` adds
`boundaryCycles` to every claim. What is *not* idealised is the hint soundness this track exists
to test — every cell above `inputCells` is still the prover's, and `Sound` still has to defend
against all of them. -/

/-- The public statement, least significant bit first: the 128-bit public key, the 256-bit
message, the signature bit length in 128 bits capped at `maxSignatureBits + 1` so every oversized
input is distinguishable from an admissible one, then the first `maxSignatureBits` signature
bits. -/
def statementBits (pk : PublicKey) (msg : Message) (σ : List Bool) : List Bool :=
  toBits pk ++ toBits msg ++
    toBits (BitVec.ofNat 128 (min σ.length (maxSignatureBits + 1))) ++
    σ.take maxSignatureBits

/-- Length of the statement: `128 + 256 + 128 + 5504 = 6016` bits. -/
def statementBitLength : ℕ := pkBits + msgBits + 128 + maxSignatureBits

/-- Blocks the statement absorbs into, `⌈6016 / 512⌉ = 12`: the number of `BLAKE2S` instructions
a program spends binding it to leanVM's 256-bit public input. -/
def statementBlocks : ℕ := (statementBitLength + blockBits - 1) / blockBits

/-- Cycles every claim carries for the public boundary leanVM actually has: one `BLAKE2S` per
statement block, `statementBlocks * weight .blake2s = 120`.

This is a floor, and a deliberately generous one. It counts the compressions and nothing else —
not the `statementBlocks` `SET_CONSTANT` instructions the per-block metadata needs (§10.8), and
not the addressing — so a faithful accounting would be at least 132. Being the same for every
submission, it never changes the ordering of records; what it changes is that the boundary cost
leanVM really has is charged rather than hidden.

It does **not** make a leanISA total comparable with a RISC-V one. The per-instruction prices
still differ: one `BLAKE2S` covers the same 512-bit block as one cycle of RISC-V's `HASH` and
costs ten, so a verifier doing `H` compressions pays about `10 · H` here and `H` there.
Subtracting the surcharge does not close that gap, and nothing in this contract licenses
comparing the two totals. The comparable quantity is the non-hashing instruction count. -/
def boundaryCycles : ℕ := statementBlocks * weight .blake2s

/-- Cells holding the signature, at 128 bits each: `⌈maxSignatureBits / 128⌉ = 43`. -/
def signatureCells : ℕ := (maxSignatureBits + 127) / 128

/-- Cells the loader pins: one public key, two message cells, one length cell and the signature
cells — 47 with the competition's constants. Derived, not written out, so that a change to
`maxSignatureBits` cannot silently drop signature bits; `check-leanisa.lean` pins the value. -/
def inputCells : ℕ := 4 + signatureCells

/-- The word pinned into cell `i`: the public key at 0, the message at 1 and 2, the capped
signature bit length at 3, then the signature at 4 and above, 128 bits per cell, least
significant bit first, zero-padded. These are `statementBits` laid out one cell per 128 bits. -/
def inputWord (pk : PublicKey) (msg : Message) (σ : List Bool) (i : ℕ) : E :=
  cellOfBits (ofBits 128 (((statementBits pk msg σ).drop (i * 128)).take 128))

/-- The committed image the machine runs on: the prover's image with the lowest `inputCells`
cells overwritten by the statement. `minLogMem = 16`, so those cells always fit. Every cell above
them is the prover's choice, and defending against every such choice is what
`LeanIsa.Submission.Sound` demands. -/
def loadInput (pk : PublicKey) (msg : Message) (σ : List Bool) {κ : ℕ}
    (L : MemImage κ) : MemImage κ :=
  fun i => if (i : ℕ) < inputCells then inputWord pk msg σ i else L i

end OptimalOTS.LeanIsa
