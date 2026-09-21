import OptimalOTS.OracleAlgorithm

/-! Internal witness, not part of the contract: `Admissible.verifyCost` is load-bearing.

`Scheme.Secure` bounds the attacker's advantage by `B / 2 ^ securityBits` for every pathwise
budget `B` of the *whole* experiment, and the experiment ends with a verification. So a scheme
whose verifier is expensive raises the right-hand side without doing anything an attacker has to
get past.

`badScheme` below has a fixed public key, accepts the empty signature on every message, and burns
one hash query on a `2 ^ 137`-bit input. That query costs `blockCost (2 ^ 137) = 2 ^ 128` on every
path, so no `B < 2 ^ 128` is a valid budget and every instance of `Secure` concludes
`probTrue < B / 2 ^ 127`, where the right-hand side is at least 2. The scheme satisfies `Secure`
(`badScheme_secure`) and is forged with probability 1 (`badScheme_forged`).

What excludes it is `Admissible.verifyCost`: `badScheme_not_admissible`. Deleting that field, or
raising `verifyBudget` above `2 ^ 128`, makes this file fail — which is the point of keeping it.
-/

namespace OptimalOTS.Witnesses.VerifyBudget

open OptimalOTS OptimalOTS.OracleAlgorithm OracleComp OracleSpec ENNReal

noncomputable section
open scoped Classical

/-! ## Two facts about the cost model -/

theorem range_nonempty (t : Spec.Domain) : Nonempty (Spec.Range t) := by
  match t with
  | .inl n => exact ⟨(0 : Fin (n + 1))⟩
  | .inr q => exact ⟨(0 : BitVec hashBits)⟩

/-- A budget for a computation is a budget for its tail: `CostAtMost` subtracts at every query,
so the budget only shrinks along a path. -/
theorem cost_tail {α β : Type} (N : ℕ) (f : α → OracleComp Spec β)
    (hf : ∀ a B, CostAtMost (f a) B → N ≤ B) :
    ∀ (oa : OracleComp Spec α) (B : ℕ), CostAtMost (oa >>= f) B → N ≤ B := by
  intro oa
  induction oa using OracleComp.inductionOn with
  | pure x => intro B h; exact hf x B (by simpa using h)
  | query_bind t k ih =>
      intro B h
      unfold CostAtMost at h
      rw [bind_assoc, isQueryBound_query_bind_iff] at h
      obtain ⟨u⟩ := range_nonempty t
      have := ih u (B - queryCost t) (h.2 u)
      omega

/-- One hash query on a `k`-bit input costs `blockCost k`, whatever follows it. -/
theorem hash_cost {k : ℕ} {β : Type} (u : BitVec k) (g : BitVec hashBits → OracleComp Spec β)
    (B : ℕ) (h : CostAtMost (hash u >>= g) B) : blockCost k ≤ B := by
  unfold CostAtMost hash at h
  rw [isQueryBound_query_bind_iff] at h
  exact h.1

theorem probTrue_le_one (oa : OracleComp Spec Bool) : probTrue oa ≤ 1 := by
  simp [probTrue]

/-- Simulating only shrinks the support, so a computation with no `true` in its raw support
outputs `true` with probability zero. -/
theorem probTrue_eq_zero_of_not_mem_support {oa : OracleComp Spec Bool}
    (h : true ∉ _root_.support oa) : probTrue oa = 0 := by
  rw [probTrue, probOutput_eq_zero_iff]
  intro hmem
  exact h (support_simulateQ_run'_subset oracleImpl oa ∅ hmem)

/-! ## The scheme -/

/-- A query width whose single-query cost is exactly `2 ^ 128`. -/
def hugeBits : ℕ := 2 ^ 137

theorem blockCost_hugeBits : blockCost hugeBits = 2 ^ 128 := by
  norm_num [blockCost, blockBits, hugeBits]

/-- Every message has the same valid signature: the empty one. -/
def badScheme : Scheme where
  SecretKey := Unit
  keygen := pure (0, ())
  sign := fun _ _ => pure (some [])
  verify := fun _ _ σ => do
    let _ ← hash (0 : BitVec hugeBits)
    pure σ.isEmpty

@[simp] theorem badScheme_keygen :
    badScheme.keygen = (pure (0, ()) : OracleComp Spec (PublicKey × badScheme.SecretKey)) := rfl
@[simp] theorem badScheme_sign (sk : badScheme.SecretKey) (m : Message) :
    badScheme.sign sk m = pure (some []) := rfl
@[simp] theorem badScheme_verify (pk : PublicKey) (m : Message) (σ : List Bool) :
    badScheme.verify pk m σ = ((fun _ => σ.isEmpty) <$> hash (0 : BitVec hugeBits)) := rfl

/-! ## It meets every requirement except the verification budget -/

theorem badScheme_correct : badScheme.Correct := by
  intro message
  refine probTrue_eq_zero_of_not_mem_support ?_
  simp [badScheme]

theorem badScheme_verifyDeterministic : badScheme.VerifyDeterministic := by
  intro pk m σ
  show Deterministic _
  rw [badScheme_verify]
  unfold Deterministic
  rw [isQueryBound_map_iff]
  unfold hash
  rw [isQueryBound_query_iff]
  rfl

theorem badScheme_signingFailure :
    badScheme.SigningFailureAtMost (1 / 2 ^ signingFailureBits) := by
  intro message
  refine le_trans (le_of_eq (probTrue_eq_zero_of_not_mem_support ?_)) zero_le
  simp [badScheme]

theorem badScheme_signatureSize : badScheme.SignatureSizeAtMost maxSignatureBits := by
  intro sk m σ hσ
  simp only [badScheme_sign, support_pure, Set.mem_singleton_iff, Option.some.injEq] at hσ
  simp [hσ, maxSignatureBits]

theorem badScheme_rejectsOversized : badScheme.RejectsOversized maxSignatureBits := by
  intro pk m σ hσ
  have hne : σ ≠ [] := by
    rintro rfl
    exact absurd hσ (by simp [maxSignatureBits])
  simp [badScheme_verify, List.isEmpty_iff, hne]

theorem badScheme_keygenCost : badScheme.KeygenCostAtMost keygenBudget := by
  show CostAtMost badScheme.keygen keygenBudget
  rw [badScheme_keygen]
  exact isQueryBound_pure _ _ _ _

theorem badScheme_signCost : badScheme.SignCostAtMost signBudget := by
  intro sk m
  show CostAtMost (badScheme.sign sk m) signBudget
  rw [badScheme_sign]
  exact isQueryBound_pure _ _ _ _

/-! ## Every experiment costs at least `2 ^ 128`, so `Secure` holds of it -/

theorem experiment_cost (A : Adversary) (B : ℕ)
    (h : CostAtMost (experiment badScheme A) B) : 2 ^ 128 ≤ B := by
  unfold experiment at h
  refine cost_tail _ _ ?_ _ B h
  rintro ⟨pk, sk⟩ B₁ h₁
  refine cost_tail _ _ ?_ _ B₁ h₁
  rintro ⟨m₁, st⟩ B₂ h₂
  refine cost_tail _ _ ?_ _ B₂ h₂
  rintro σ₁ B₃ h₃
  refine cost_tail _ _ ?_ _ B₃ h₃
  rintro ⟨m₂, σ₂⟩ B₄ h₄
  dsimp only at h₄
  rw [badScheme_verify, map_eq_bind_pure_comp, bind_assoc] at h₄
  have := hash_cost _ _ _ h₄
  rwa [blockCost_hugeBits] at this

theorem badScheme_secure : badScheme.Secure := by
  intro A B hB
  have hge : 2 ^ 128 ≤ B := experiment_cost A B hB
  have hc : ((2 : ℝ≥0∞) ^ 128) ≤ (B : ℝ≥0∞) := by
    exact_mod_cast (Nat.cast_le (α := ℝ≥0∞)).mpr hge
  have h2 : (2 : ℝ≥0∞) ≤ (B : ℝ≥0∞) / 2 ^ securityBits := by
    calc (2 : ℝ≥0∞) = 2 ^ 128 / 2 ^ securityBits := by
          rw [securityBits, show (2:ℝ≥0∞) ^ 128 = 2 * 2 ^ 127 by ring, mul_div_assoc,
            ENNReal.div_self (by positivity) (by finiteness), mul_one]
      _ ≤ (B : ℝ≥0∞) / 2 ^ securityBits := ENNReal.div_le_div_right hc _
  exact lt_of_le_of_lt (probTrue_le_one _) (lt_of_lt_of_le (by norm_num) h2)

/-! ## And yet it is forged with probability 1 -/

/-- Ask for a signature on message `0`, hand the same empty signature back on message `1`. -/
def forger : Adversary where
  State := Unit
  choose := fun _ => pure (0, ())
  forge := fun _ _ => pure (1, [])

theorem badScheme_forged : probTrue (experiment badScheme forger) = 1 := by
  unfold experiment forger
  simp [badScheme, probTrue, Prod.ext_iff]
  simp [msgBits]

/-! ## What excludes it -/

theorem badScheme_verify_cost_is_huge : ¬ badScheme.VerifyCostAtMost verifyBudget := by
  intro h
  have hv := h 0 0 []
  rw [badScheme_verify, map_eq_bind_pure_comp] at hv
  have hcost := hash_cost _ _ _ hv
  rw [blockCost_hugeBits, verifyBudget] at hcost
  norm_num at hcost

/-- `Secure` alone is satisfied by a scheme anyone can forge; `Admissible.verifyCost` is the
clause that rules it out. -/
theorem badScheme_not_admissible : ¬ badScheme.Admissible :=
  fun h => badScheme_verify_cost_is_huge h.verifyCost

/-- The witness in one statement. -/
theorem verifyCost_is_load_bearing :
    badScheme.Secure ∧ probTrue (experiment badScheme forger) = 1 ∧
      ¬ badScheme.Admissible :=
  ⟨badScheme_secure, badScheme_forged, badScheme_not_admissible⟩

end

end OptimalOTS.Witnesses.VerifyBudget
