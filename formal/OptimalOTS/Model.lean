import VCVio.OracleComp.QueryTracking.RandomOracle.Basic
import VCVio.OracleComp.QueryTracking.QueryBound.Basic
import VCVio.OracleComp.Constructions.SampleableType
import VCVio.OracleComp.SimSemantics.Append
import VCVio.OracleComp.ProbComp
import VCVio.EvalDist.BitVec

/-!
# The shared model

The competition's constants, the random oracle, and the cost of a query. Every model
(`Dag.lean`, `OracleAlgorithm.lean`, `RiscvMachine.lean`) builds on this file. All parties
share one random oracle on bit strings, without implicit labels or domain separation. Uniform
sampling is free; every hash query is charged for its complete input, including repeated queries.
-/

open OracleSpec OracleComp ENNReal

noncomputable section

open scoped Classical

namespace OptimalOTS

/-! ## 1. Constants

Lengths are in bits, costs in compressions. -/

/-- Output length of the random oracle. -/
def hashBits : ℕ := 256
/-- Input bits per compression: hashing `k` bits costs `max 1 ⌈k / blockBits⌉`. -/
def blockBits : ℕ := 512
/-- Public-key length. -/
def pkBits : ℕ := 128
/-- Message length. -/
def msgBits : ℕ := 256
/-- Security level: an attack with budget `B` succeeds with probability below
`B / 2 ^ securityBits`. -/
def securityBits : ℕ := 127
/-- Maximal signature length, including any nonce. -/
def maxSignatureBits : ℕ := 5504
/-- Maximal cost of key generation. -/
def keygenBudget : ℕ := 2 ^ 20
/-- Maximal cost of signing. -/
def signBudget : ℕ := 2 ^ 20
/-- Maximal cost of verification. Verification is part of the security experiment, so an
unbounded verifier would inflate every attack budget `B` and make the security statement
vacuous; this caps that inflation at the same budget key generation and signing get. -/
def verifyBudget : ℕ := 2 ^ 20
/-- Signing may fail with probability at most `1 / 2 ^ signingFailureBits`. -/
def signingFailureBits : ℕ := 128

abbrev Message := BitVec msgBits
abbrev PublicKey := BitVec pkBits

/-! ## 2. The random oracle and the cost of a query -/

/-- A bit string of any length, used as a random-oracle input. There are no implicit labels or
tweaks: equal strings share an answer. Explicit prefixes are part of the input and incur their
full query cost. -/
abbrev Query := Σ k : ℕ, BitVec k

/-- The random oracle: an independent uniform `hashBits`-bit answer for every query. -/
abbrev hashSpec : OracleSpec Query := Query →ₒ BitVec hashBits

/-- The oracles of every party: free uniform sampling and the random oracle. -/
abbrev Spec := unifSpec + hashSpec

/-- Cost of hashing `k` bits: the number of started blocks, and at least one. -/
def blockCost (k : ℕ) : ℕ := max 1 ((k + blockBits - 1) / blockBits)

/-- Cost of a query: uniform sampling is free, hashing `k` bits costs `blockCost k`. -/
def queryCost : Spec.Domain → ℕ
  | .inl _ => 0
  | .inr q => blockCost q.1

/-- `oa` costs at most `B` on every execution path, whatever the oracle answers. -/
def CostAtMost {α : Type} (oa : OracleComp Spec α) (B : ℕ) : Prop :=
  oa.IsQueryBound B (fun t b => queryCost t ≤ b) (fun t b => b - queryCost t)

/-- Raising the budget preserves a cost bound: the per-query test `queryCost t ≤ b` is upward
closed in `b`, and the budget left after a query is monotone in it. A submission that proves a
tight verification cost meets `verifyBudget` through this. -/
theorem CostAtMost.mono {α : Type} {oa : OracleComp Spec α} :
    ∀ {b b' : ℕ}, CostAtMost oa b → b ≤ b' → CostAtMost oa b' := by
  induction oa using OracleComp.inductionOn with
  | pure x => intro b b' _ _; trivial
  | query_bind t k ih =>
      intro b b' h hle
      unfold CostAtMost at h ⊢
      rw [isQueryBound_query_bind_iff] at h ⊢
      exact ⟨le_trans h.1 hle, fun u => ih u (h.2 u) (Nat.sub_le_sub_right hle _)⟩

/-- `oa` uses no private randomness: on every path, every query goes to the hash oracle. -/
def Deterministic {α : Type} (oa : OracleComp Spec α) : Prop :=
  oa.IsQueryBound () (fun t _ => t.isRight = true) (fun _ u => u)

/-- Query the random oracle on input `u`. -/
def hash {k : ℕ} (u : BitVec k) : OracleComp Spec (BitVec hashBits) :=
  liftM (Spec.query (.inr ⟨k, u⟩))

/-- Sample a uniform bit string (free). -/
def sampleBits (n : ℕ) : OracleComp Spec (BitVec n) :=
  liftM ($ᵗ BitVec n : ProbComp (BitVec n))

/-- Random-oracle semantics: uniform sampling is forwarded, and every hash query is answered by
one lazily sampled table shared by the whole experiment. -/
def oracleImpl : QueryImpl Spec (StateT hashSpec.QueryCache ProbComp) :=
  (HasQuery.toQueryImpl (spec := unifSpec) (m := ProbComp)).liftTarget
      (StateT hashSpec.QueryCache ProbComp) +
    randomOracle (spec := hashSpec)

/-- Probability that a Boolean experiment outputs `true` in the random-oracle model. -/
def probTrue (oa : OracleComp Spec Bool) : ℝ≥0∞ :=
  Pr[= true | (simulateQ oracleImpl oa).run' ∅]

/-! ## 3. Bit strings -/

/-- The bits of `x`, least significant first. -/
def toBits {n : ℕ} (x : BitVec n) : List Bool := List.ofFn fun i : Fin n => x.getLsbD i

/-- Interpret the list least significant bit first, truncating or zero-extending to `n` bits. -/
def ofBits (n : ℕ) (l : List Bool) : BitVec n :=
  BitVec.ofNat n (l.foldr (fun b acc => b.toNat + 2 * acc) 0)

end OptimalOTS
