import OptimalOTS.OracleAlgorithm
import OptimalOTS.LeanIsaMachine

/-!
# leanISA upper submissions

A submission is an oracle-algorithm scheme — the *specification* of a one-time signature —
together with a leanISA bytecode that is supposed to *implement* its verifier, and the witnesses
an honest prover would supply.

`Riscv.lean` ties its image to its scheme with a single equation, because a RISC-V run is a
function of the input and the oracle's answers. A leanISA run is not: the prover commits the
memory, so the machine's acceptance is "some committed image completes the run". That existential
cannot be written inside an `OracleComp`, and even for the honest prover the two computations do
not have the same shape — the prover queries each hash to learn the word it must commit, and the
machine queries it again to check the committed cell. They agree under one cached oracle and not
as syntax. So the tie is made of two clauses instead of one, both stated with `probTrue`, whose
`oracleImpl` is the shared lazily-sampled `randomOracle`:

* `Faithful` — the honest prover's image reproduces the verifier's decision, both ways.
* `Sound` — **no** prover-chosen image, at any admissible memory size, makes the machine complete
  on an input the verifier rejects.

`Sound` is the clause that does the work this track exists for. Every memory cell above the
statement is the prover's, so `Sound` is what forces a program to constrain each one it reads.
An under-constrained program has a second image that completes on a rejected signature, and
fails here.

`Sound` alone would be satisfied by a program with no valid execution at all — one that never
completes vacuously accepts nothing it should not. `Faithful` alone would be satisfied by an
under-constrained program: one whose honest image tracks the verifier while a second image also
completes, on an input the verifier rejects. Together they pin the machine's acceptance predicate
to `scheme.verify`, which is what carries `Admissible` and `Secure` onto the machine.
-/

namespace OptimalOTS.LeanIsa

open LeanerVM.Parameters LeanerVM.Semantics OracleComp

/-- An OTS specification, the bytecode meant to check it, and the prover's witnesses.

`memLog` is the memory log-size `κ_mem` the submission announces. `prover` is the honest
memory-filling strategy; it is an oracle computation because the image it commits contains hash
outputs, which the prover can only learn by querying. `steps` is the instruction count that
witnesses termination.

Neither `prover` nor `steps` is an input to the machine, and neither can lower the score: they
appear only in `Faithful`, while `CyclesAtMost` ranges over every image and every step count. -/
structure Submission where
  /-- The one-time signature this submission claims to implement. -/
  scheme : OracleAlgorithm.Scheme
  /-- The fixed leanISA bytecode. -/
  program : Program
  /-- The announced memory log-size `κ_mem`. -/
  memLog : ℕ
  /-- The honest prover's committed memory, per raw input. -/
  prover : PublicKey → Message → List Bool → OracleComp Spec (MemImage memLog)
  /-- The instruction count of the honest execution, per raw input. -/
  steps : PublicKey → Message → List Bool → ℕ

/-- Rows the prover must seed and finalize whatever the program does: one per bytecode slot and
one per cell of the announced memory.

This is the leanISA counterpart of `Riscv.Image.byteSize`. It is not part of the score — the
score counts executed instructions — and that is precisely why it is bounded separately: the
seed and finalize phases pay two bus flushes per row over every slot and every cell, touched or
not, and no per-opcode weight reflects that. `Submission.Certificate` does not mention it; the
track's stub requires a separate exported theorem bounding it by `maxSeededRows`, which the
comparator checks with the same statement comparison, axiom audit and kernel replay as the
cycle certificate. -/
def Submission.seededRows (S : Submission) : ℕ := 2 ^ S.program.logSize + 2 ^ S.memLog

/-- The machine run on one raw input over one committed image: `some cost` when the image drives
`n` instructions from `(1, 1)` to the sentinel, `none` otherwise.

The loader pins the statement into the lowest `inputCells` cells; every cell above them is the
prover's choice. That boundary is wider than leanVM's own 256 bits, deliberately and for a
reason `LeanIsaMachine.lean` section 7 gives in full; `Submission.CyclesAtMost` charges
`boundaryCycles` for the difference. -/
noncomputable def Submission.exec (S : Submission) {κ : ℕ} (L : MemImage κ) (n : ℕ)
    (pk : PublicKey) (m : Message) (σ : List Bool) : OracleComp Spec (Option ℕ) :=
  runCost S.program (loadInput pk m σ L) n Regs.initial

/-- Soundness: no prover makes the machine accept what the verifier rejects.

`probTrue x = 0` says the bad event occurs on **no** path of the cached simulation, not merely
with probability zero: every coherent answer assignment has positive probability, so
`probTrue x = 0 ↔ true ∉ support ((simulateQ oracleImpl x).run' ∅)`
(`scripts/check-leanisa.lean`, `probTrue_eq_zero_iff`). That is the support of the *simulated*
computation, in which repeated queries agree; it is not `true ∉ support x`, which would also
forbid incoherent answer paths and is strictly stronger. `κ` ranges over every memory size the
instance caps admit, not just the one the submission announces, because the prover announces
`κ` too.

The image and step count are quantified plainly. That is not weaker than quantifying an
oracle-adaptive prover strategy `P : OracleComp Spec (MemImage κ × ℕ)`, and this is a theorem
rather than a remark: `scripts/check-leanisa.lean` proves `Submission.sound_adaptive`, which
derives the adaptive form from this one. A winning path of the adaptive experiment runs `P` to
some image and step count and some oracle cache, then runs the machine and the verifier from
that cache; cache weakening restricts the tail to a path from the empty cache, which this clause
at that very image and step count forbids. Stating it plainly therefore spares every submission
an induction over an arbitrary free monad for no loss of strength.

`probTrue` — not `support` — is essential here. The machine and the verifier both hash, and only
the cached simulation makes them see the same answer for the same query; under `support` they
could diverge and no real submission could discharge this.

This is the clause that tests whether a leanISA program is fully constrained. An
under-constrained program has a second image that completes on a signature the specification
rejects, and fails here. -/
def Submission.Sound (S : Submission) : Prop :=
  ∀ (pk : PublicKey) (m : Message) (σ : List Bool) (κ : ℕ),
    minLogMem ≤ κ → κ ≤ maxLogMem →
    ∀ (L : MemImage κ) (n : ℕ),
      probTrue (do
        let outcome ← S.exec L n pk m σ
        let accepted ← S.scheme.verify pk m σ
        pure (outcome.isSome && !accepted)) = 0

/-- The machine driven by the submission's own prover: `true` when the committed image carries
the run to the sentinel in `steps` instructions. -/
noncomputable def Submission.honestRun (S : Submission) (pk : PublicKey) (m : Message)
    (σ : List Bool) : OracleComp Spec Bool := do
  let L ← S.prover pk m σ
  (fun outcome => outcome.isSome) <$> S.exec L (S.steps pk m σ) pk m σ

/-- Faithfulness: the announced memory size is within the instance caps, and on every raw input
the honest prover's run agrees with the Lean verifier in both directions — it completes exactly
when verification accepts.

This is the counterpart of `Riscv.Submission.Implements`: agreement of decisions under the shared
cached oracle, in place of equality of oracle computations. It is what rules out a bytecode that
no image can ever run to completion. -/
def Submission.Faithful (S : Submission) : Prop :=
  minLogMem ≤ S.memLog ∧ S.memLog ≤ maxLogMem ∧
    ∀ (pk : PublicKey) (m : Message) (σ : List Bool),
      probTrue (do
        let completed ← S.honestRun pk m σ
        let accepted ← S.scheme.verify pk m σ
        pure (completed != accepted)) = 0

/-- Every completing execution costs at most `c` cycles, under every admissible memory size,
every committed image and every step count — not only the submission's own witnesses.

The claim covers `boundaryCycles` as well as the executed instructions. leanVM's public input is
256 bits, so a real program would spend twelve `BLAKE2S` binding this competition's 6016-bit
statement to it; the loader idealises that away, and this surcharge is where the idealisation is
paid for. It is the same constant for every submission, so it never reorders records. It does
not make a leanISA total comparable with a RISC-V one: `weight .blake2s = 10` against RISC-V's
one cycle per 512-bit `HASH` block leaves a factor of ten on every compression that no constant
absorbs. See `LeanIsaMachine.boundaryCycles`.

This clause is stated over `support`, as `Riscv.Submission.CyclesAtMost` is, and `support` has
**no oracle cache**: each query independently ranges over every answer. So the bound must hold
even on incoherent answer paths, where the `BLAKE2S` rows constrain nothing — given any canonical
nine cells, an answer matching the committed output pair exists, so a run can complete here that
`Sound` rules out. That is deliberate and conservative, and it has a consequence a submitter must
plan for: **the cycle count may not depend on hash binding.** Jump targets and loop lengths have
to be pinned by the non-`BLAKE2S` constraints, or by the size of the bytecode, rather than by the
value of a hash. Bytecode size is no help: `JUMP` reads its destination from a memory cell, so
`2 ^ κ_bc` bounds the number of distinct slots and not the run length. Any loop that advances
`fp` into fresh frames and tests an unpinned cell to exit has completing runs of every length,
and fails this clause.

Because `support` and `probTrue` are different semantics, this clause does not compose with
`Sound` into a single statement; each is a separate obligation about the same program.

Rejecting runs are not charged, because in this model they do not exist: a rejected input is one
no image completes. The score is therefore the worst case of an *accepted* verification, which is
what a prover actually pays. Quantifying over all images is what stops a program whose honest run
is short but whose hint-controlled loop admits an arbitrarily long completing run. -/
def Submission.CyclesAtMost (S : Submission) (c : ℕ) : Prop :=
  ∀ (pk : PublicKey) (m : Message) (σ : List Bool) (κ : ℕ),
    minLogMem ≤ κ → κ ≤ maxLogMem →
    ∀ (L : MemImage κ) (n cost : ℕ),
      some cost ∈ support (S.exec L n pk m σ) → boundaryCycles + cost ≤ c

/-- The certificate for claim `c`.

`admissible` and `secure` pin the specification to a real 127-bit strongly unforgeable OTS.
`faithful` and `sound` pin the bytecode to that specification in both directions: together they
make machine acceptance and `scheme.verify` agree on every oracle assignment, which is what
carries admissibility and security onto the machine. `valid` bounds the bytecode, without which a
free lookup table would absorb every non-hash cost. `cycles` then measures a program that really
has to run the verification: `Admissible.correct` forces `scheme.verify` to accept something, so
`faithful` forces a completing honest run, and `secure` forces that run to hash.

`cycles` is stated over `support` while `faithful` and `sound` are stated over `probTrue`, so the
three are separate obligations in two different oracle semantics rather than one argument; see
each clause for what it does and does not say. -/
structure Submission.Certificate (S : Submission) (c : ℕ) : Prop where
  /-- Correctness, deterministic verification, bounded signing failure, and the size and cost
  budgets of the competition. -/
  admissible : S.scheme.Admissible
  /-- Strong unforgeability in the shared random-oracle experiment. -/
  secure : S.scheme.Secure
  /-- The bytecode fits the instruction budget and has no `JUMP` in its halt slot. -/
  valid : BytecodeValid S.program
  /-- The honest prover's image reproduces the verifier's decision on every input. -/
  faithful : S.Faithful
  /-- No prover-chosen image makes the machine complete on a rejected input. -/
  sound : S.Sound
  /-- Every completing execution, under every image, costs at most `c` cycles. -/
  cycles : S.CyclesAtMost c

end OptimalOTS.LeanIsa
