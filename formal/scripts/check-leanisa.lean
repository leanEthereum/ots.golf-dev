import OptimalOTS.LeanIsa

/-! Kernel-checked boundary tests for the leanISA machine and derived facts about the leanISA
contract, not OTS certificates.

`LeanerVM.Semantics.Program.fetch` and `MemImage.read` go through `gLog?`, which is
`Classical.choose`-based, so nothing about a *run* reduces in the kernel: unlike
`check-riscv.lean`, these tests cannot execute a program. What they pin instead is everything
the score is computed from — the weights, the public-boundary arithmetic, the bytecode caps,
the shape of the oracle query, and the exact points at which each certificate clause is
vacuous. -/

open OptimalOTS OptimalOTS.LeanIsa LeanerVM.Parameters LeanerVM.Semantics OracleComp

namespace LeanIsaChecks

/-- `toBits` is `List.ofFn` over the index type, so its length is the bit width. Stated once:
unfolding it on a literal width expands into that many `List.cons`es. -/
private theorem length_toBits {n : ℕ} (x : BitVec n) : (toBits x).length = n := by
  simp [toBits]

/-! ## 1. The cost model

Every opcode costs at least one cycle and only `BLAKE2S` costs more, so the score is the
executed-instruction count plus nine per `BLAKE2S`. -/

example : weight .xor = 1 := rfl
example : weight .mulNative = 1 := rfl
example : weight .setConstant = 1 := rfl
example : weight .deref = 1 := rfl
example : weight .jump = 1 := rfl
example : weight .blake2s = 10 := rfl

example : ∀ op : Opcode, op ≠ .blake2s → weight op = 1 := by
  rintro (_ | _ | _ | _ | _ | _) h <;> first | rfl | exact absurd rfl h

example : ∀ op : Opcode, 1 ≤ weight op := by
  rintro (_ | _ | _ | _ | _ | _) <;> decide

/-! ## 2. The public-boundary surcharge

The loader pins the statement into whole cells with no slack and no truncation, and the
surcharge is one `BLAKE2S` per started 512-bit block of it. -/

example : statementBitLength = 6016 := rfl
example : statementBlocks = 12 := rfl
example : signatureCells = 43 := rfl
example : inputCells = 47 := rfl
example : boundaryCycles = 120 := rfl

-- The surcharge is the per-block price of the statement, not a constant written by hand.
example : boundaryCycles = statementBlocks * weight .blake2s := rfl

-- 12 is exactly the number of started blocks: 11 blocks are too few, 12 suffice.
example : statementBitLength ≤ statementBlocks * blockBits := by decide
example : (statementBlocks - 1) * blockBits < statementBitLength := by decide

-- The pinned cells hold the statement exactly: no signature bit is dropped, no cell is wasted.
example : inputCells * 128 = statementBitLength := rfl
example : pkBits + msgBits + 128 = 4 * 128 := rfl
example : maxSignatureBits = signatureCells * 128 := rfl

-- The loader always fits: `minLogMem = 16` gives 65536 cells for 47.
example : inputCells < 2 ^ minLogMem := by decide

/-! ## 3. The statement is a faithful, injective encoding of the raw input

The length cell is capped at `maxSignatureBits + 1`, so an oversized signature is
distinguishable from every admissible one even though its bits are truncated. -/

-- A short signature makes a short statement; `inputWord` zero-pads it into whole cells.
example (pk : PublicKey) (msg : Message) (σ : List Bool) :
    (statementBits pk msg σ).length ≤ statementBitLength := by
  simp only [statementBits, statementBitLength, List.length_append, length_toBits,
    List.length_take]
  simp only [pkBits, msgBits, maxSignatureBits]
  omega

-- At the size limit the statement fills every pinned cell exactly.
example (pk : PublicKey) (msg : Message) (σ : List Bool) (h : maxSignatureBits ≤ σ.length) :
    (statementBits pk msg σ).length = statementBitLength := by
  simp only [maxSignatureBits] at h
  simp only [statementBits, statementBitLength, List.length_append, length_toBits,
    List.length_take]
  simp only [pkBits, msgBits, maxSignatureBits]
  omega

/-! ## 4. Cells and bit strings -/

example (b : BitVec 128) : cellBits (cellOfBits b) = b := cellBits_cellOfBits b
example (b : BitVec 128) : IsCanonical128 (cellOfBits b) := by
  simp [IsCanonical128, cellOfBits]

/-! ## 5. The oracle query

`BLAKE2S` queries the one shared oracle on exactly the 896 bits it consumes, in the order the
specification fixes. These guards break if the layout is ever reordered. -/

example (cv : BitVec 256) (block : BitVec 512) (md : BitVec 128) :
    hashInput cv block md = ofBits 896 (toBits cv ++ toBits block ++ toBits md) := rfl

example (m : Fin 4 → E) (cv0 cv1 md : E) :
    blake2sQuery m cv0 cv1 md
      = hashInput (cellBits cv1 ++ cellBits cv0)
          (cellBits (m 3) ++ cellBits (m 2) ++ cellBits (m 1) ++ cellBits (m 0))
          (cellBits md) := rfl

example (cv : BitVec 256) (block : BitVec 512) (md : BitVec 128) :
    (toBits cv ++ toBits block ++ toBits md).length = 896 := by
  simp only [List.length_append, length_toBits]

-- The query is one compression in the shared metric, so the two tracks' hash steps line up.
example : blockCost 896 = 2 := by decide
example : blockCost blockBits = 1 := by decide

/-! ## 6. Well-formed bytecode

`BytecodeValid` rejects an oversized bytecode and a `JUMP` in the halt slot, and accepts an
inert halt slot. -/

/-- A one-slot bytecode whose only slot — the halt slot — holds a `JUMP`. -/
def jumpAtSentinel : Program where
  logSize := 0
  logSize_le := by decide
  code := fun _ => .jump 1 1 1

/-- The same bytecode with an inert halt slot. -/
def inertSentinel : Program where
  logSize := 0
  logSize_le := by decide
  code := fun _ => .setConstant 1 0

/-- A bytecode one slot-decade over the competition's cap, but inside leanerVM's own. -/
def oversized : Program where
  logSize := maxProgramLogSize + 1
  logSize_le := by decide
  code := fun _ => .setConstant 1 0

example : ¬ BytecodeValid jumpAtSentinel := by decide
example : BytecodeValid inertSentinel := by decide
example : ¬ BytecodeValid oversized := by decide

-- The competition's cap is the RISC-V instruction cap, and is strictly inside leanerVM's.
example : maxProgramLogSize = 18 := rfl
example : 2 ^ maxProgramLogSize = 262144 := rfl
example : maxProgramLogSize < maxLogBytecode := by decide

/-! ### The seed and finalize budget

`seededRows` counts both tables, and its upper boundary is strict. The budget is blind to what
the execution does: an untouched slot and an untouched cell cost the same as a used one. -/

example : maxSeededRows = 1048576 := rfl

-- Both terms are counted, and the smallest admissible instance fits with room to spare.
example (S : Submission) : S.seededRows = 2 ^ S.program.logSize + 2 ^ S.memLog := rfl
example : (2:ℕ) ^ 0 + 2 ^ minLogMem < maxSeededRows := by norm_num [minLogMem, maxSeededRows]

-- The full bytecode fits beside eight times the minimum memory, and not beside sixteen.
example : (2:ℕ) ^ maxProgramLogSize + 2 ^ 19 < maxSeededRows := by
  norm_num [maxProgramLogSize, maxSeededRows]
example : ¬ (2:ℕ) ^ maxProgramLogSize + 2 ^ 20 < maxSeededRows := by
  norm_num [maxProgramLogSize, maxSeededRows]

-- The boundary is strict, and the memory alone can exhaust it.
example : ¬ (2:ℕ) ^ 0 + 2 ^ 20 < maxSeededRows := by norm_num [maxSeededRows]
example : ¬ (2:ℕ) ^ 0 + 2 ^ maxLogMem < maxSeededRows := by norm_num [maxLogMem, maxSeededRows]

-- `BytecodeValid` alone does not imply the budget: it caps the bytecode and says nothing about
-- the announced memory, which is where the unbounded cost was.
example : BytecodeValid inertSentinel ∧ ¬ (2:ℕ) ^ inertSentinel.logSize + 2 ^ maxLogMem
    < maxSeededRows := by
  refine ⟨by decide, ?_⟩
  norm_num [inertSentinel, maxLogMem, maxSeededRows]

/-! ## 7. The loop

The halting test runs before each fetch, so the halt slot never executes and a run that has
arrived costs nothing more. -/

example (prog : Program) {κ : ℕ} (L : MemImage κ) :
    runCost prog L 0 (Regs.final prog) = pure (some 0) := by
  simp [runCost, Regs.final]

example (prog : Program) {κ : ℕ} (L : MemImage κ) {r : Regs K} (h : r.pc ≠ prog.finalPc) :
    runCost prog L 0 r = pure none := by
  simp [runCost, h]

example (prog : Program) {κ : ℕ} (L : MemImage κ) (n : ℕ) {r : Regs K}
    (h : r.pc = prog.finalPc) : runCost prog L (n + 1) r = pure none := by
  simp [runCost, h]

-- Arriving with the frame pointer away from home is not an arrival.
example (prog : Program) {κ : ℕ} (L : MemImage κ) {r : Regs K} (h : r.fp ≠ 1) :
    runCost prog L 0 r = pure none := by
  simp only [runCost, if_neg (fun hc : _ ∧ _ => h hc.2)]

-- A counter that fetches nothing ends the run; in this model that is no execution, not a reject.
example (prog : Program) {κ : ℕ} (L : MemImage κ) (n : ℕ) {r : Regs K}
    (hpc : r.pc ≠ prog.finalPc) (hf : prog.fetch r.pc = none) :
    runCost prog L (n + 1) r = pure none := by
  simp [runCost, hpc, hf]

/-! ## 8. Away from `BLAKE2S` this is leanerVM

The five non-hash arms call `LeanerVM.Semantics.execute`, so they cannot drift from the pin. -/

example {κ : ℕ} (L : MemImage κ) (r : Regs K) (a b c : K) :
    LeanIsa.execute L r (.xor a b c)
      = pure (LeanerVM.Semantics.execute L r (.xor a b c)) :=
  execute_eq_leanerVM L r (.xor a b c) (by simp [Instr.opcode])

example {κ : ℕ} (L : MemImage κ) (r : Regs K) (a b c : K) :
    LeanIsa.execute L r (.mulNative a b c)
      = pure (LeanerVM.Semantics.execute L r (.mulNative a b c)) :=
  execute_eq_leanerVM L r (.mulNative a b c) (by simp [Instr.opcode])

example {κ : ℕ} (L : MemImage κ) (r : Regs K) (o : K) (k : E) :
    LeanIsa.execute L r (.setConstant o k)
      = pure (LeanerVM.Semantics.execute L r (.setConstant o k)) :=
  execute_eq_leanerVM L r (.setConstant o k) (by simp [Instr.opcode])

example {κ : ℕ} (L : MemImage κ) (r : Regs K) (a b c : K) (mode : DerefMode) :
    LeanIsa.execute L r (.deref a b c mode)
      = pure (LeanerVM.Semantics.execute L r (.deref a b c mode)) :=
  execute_eq_leanerVM L r (.deref a b c mode) (by simp [Instr.opcode])

example {κ : ℕ} (L : MemImage κ) (r : Regs K) (a b c : K) :
    LeanIsa.execute L r (.jump a b c)
      = pure (LeanerVM.Semantics.execute L r (.jump a b c)) :=
  execute_eq_leanerVM L r (.jump a b c) (by simp [Instr.opcode])

end LeanIsaChecks

/-! ## 9. Derived facts about the contract

Checked here rather than in the protected files, as `check-riscv.lean` does. -/

namespace OptimalOTS.LeanIsa

open OptimalOTS OptimalOTS.LeanIsa LeanerVM.Parameters LeanerVM.Semantics OracleComp

/-- What `probTrue … = 0` means in the clauses that use it. Zero probability is the *absence of
a path*: the experiment outputs `true` on no execution of the cached random-oracle simulation.

This is the support of the **simulated** computation, where a repeated query returns the cached
answer. It is weaker than `true ∉ support oa`, which also quantifies over incoherent answer
paths, and it is the reading `Submission.Sound` and `Submission.Faithful` rely on: the machine
and the verifier must see the same answer for the same query, as they do in reality. -/
theorem probTrue_eq_zero_iff (oa : OracleComp Spec Bool) :
    probTrue oa = 0 ↔ true ∉ support ((simulateQ oracleImpl oa).run' ∅) :=
  probOutput_eq_zero_iff _ _

/-- `CyclesAtMost` is vacuous on its own: a bytecode no committed image can run to the sentinel
satisfies every bound, because the hypothesis of each instance is unreachable.

This is why the certificate also carries `Faithful`. Together with `Admissible.correct`, which
forces `scheme.verify` to accept an honest signature, `Faithful` forces the honest prover's run
to complete, so the bound is a bound on something. -/
theorem Submission.cyclesAtMost_of_no_completion (S : Submission) (c : ℕ)
    (h : ∀ (pk : PublicKey) (m : Message) (σ : List Bool) (κ : ℕ) (L : MemImage κ) (n cost : ℕ),
      some cost ∉ support (S.exec L n pk m σ)) :
    S.CyclesAtMost c :=
  fun pk m σ κ _ _ L n cost hmem => absurd hmem (h pk m σ κ L n cost)

/-- `Sound` is equally vacuous on such a bytecode, and for the same reason: with no completing
execution the conjunct `outcome.isSome` is never `true`. Neither clause alone says a program
checks anything; `Faithful` is what makes them bite. -/
theorem Submission.sound_of_never_completes (S : Submission)
    (h : ∀ (pk : PublicKey) (m : Message) (σ : List Bool) (κ : ℕ) (L : MemImage κ) (n : ℕ),
      S.exec L n pk m σ = pure none) :
    S.Sound := by
  intro pk m σ κ _ _ L n
  rw [probTrue_eq_zero_iff]
  simp [h pk m σ κ L n]

/-! ### Cache weakening

`Sound` quantifies the committed image and the step count plainly, and `LeanIsa.lean` records
that this is no weaker than quantifying an oracle-adaptive prover. `Submission.sound_adaptive`
below is that claim, proved. The one ingredient is antitonicity of the simulation in its
starting cache: a path that runs from a populated cache also runs from a smaller one, because
the lazily-sampled oracle is free to sample exactly the entries the larger cache already held.
`VCVio` has the opposite direction (`OracleComp.simulateQ_cachingOracle_cache_le`: the cache
only grows); this direction is proved here by induction on the free monad. -/

/-- `c₂` is a subcache of `c₁`: every entry of `c₂` is an entry of `c₁`.

This is the relation `OracleSpec.QueryCache`'s `PartialOrder` gives, written out rather than as
`≤` because `QueryCache` is a reducible `Pi` type and the pointwise `Pi` order is also in scope
for it. -/
private def Subcache (c₂ c₁ : hashSpec.QueryCache) : Prop :=
  ∀ ⦃t : hashSpec.Domain⦄ ⦃u : hashSpec.Range t⦄, c₂ t = some u → c₁ t = some u

/-- One simulated query is antitone in the starting cache. Uniform sampling ignores the cache.
For a hash query, a hit in `c₁` that misses in `c₂` is reproduced by sampling the cached value —
every answer is in the support of the uniform sample — and a miss in `c₁` is a miss in `c₂`. In
both cases the two resulting caches are again in the relation. -/
private theorem subcache_step (t : Spec.Domain) (c₁ c₂ : hashSpec.QueryCache)
    (h : Subcache c₂ c₁) (u : Spec.Range t) (c₁' : hashSpec.QueryCache)
    (hmem : (u, c₁') ∈ support ((oracleImpl t).run c₁)) :
    ∃ c₂', Subcache c₂' c₁' ∧ (u, c₂') ∈ support ((oracleImpl t).run c₂) := by
  match t with
  | .inl n =>
      have h₁ : (oracleImpl (.inl n)).run c₁
          = (fun a => (a, c₁)) <$> (HasQuery.toQueryImpl (spec := unifSpec) (m := ProbComp) n) :=
        rfl
      have h₂ : (oracleImpl (.inl n)).run c₂
          = (fun a => (a, c₂)) <$> (HasQuery.toQueryImpl (spec := unifSpec) (m := ProbComp) n) :=
        rfl
      rw [h₁, support_map] at hmem
      obtain ⟨x, hx, hxe⟩ := hmem
      simp only [Prod.mk.injEq] at hxe
      obtain ⟨rfl, rfl⟩ := hxe
      exact ⟨c₂, h, by rw [h₂, support_map]; exact ⟨x, hx, rfl⟩⟩
  | .inr q =>
      have h₁ : (oracleImpl (.inr q)).run c₁ = (hashSpec.randomOracle q).run c₁ := rfl
      have h₂ : (oracleImpl (.inr q)).run c₂ = (hashSpec.randomOracle q).run c₂ := rfl
      rw [h₁, randomOracle.run_eq] at hmem
      rw [h₂, randomOracle.run_eq]
      cases hc₁ : c₁ q with
      | some v =>
          rw [hc₁] at hmem
          simp only [support_pure, Set.mem_singleton_iff, Prod.mk.injEq] at hmem
          obtain ⟨hu, hc⟩ := hmem
          subst hu
          subst hc
          cases hc₂ : c₂ q with
          | some w =>
              have hw : c₁' q = some w := h hc₂
              rw [hc₁] at hw
              have huw : u = w := Option.some.inj hw
              refine ⟨c₂, h, ?_⟩
              show (u, c₂) ∈ support (pure (w, c₂) : ProbComp _)
              simp [huw]
          | none =>
              refine ⟨c₂.cacheQuery q u, ?_, ?_⟩
              · intro t' u' ht'
                rcases eq_or_ne t' q with rfl | hne
                · rw [OracleSpec.QueryCache.cacheQuery_self] at ht'
                  exact hc₁.trans (congrArg some (Option.some.inj ht'))
                · rw [OracleSpec.QueryCache.cacheQuery_of_ne _ _ hne] at ht'
                  exact h ht'
              · show (u, c₂.cacheQuery q u) ∈
                  support (($ᵗ hashSpec.Range q) >>= fun w => pure (w, c₂.cacheQuery q w))
                rw [mem_support_bind_iff]
                exact ⟨u, mem_support_uniformSample _, by simp⟩
      | none =>
          replace hmem : (u, c₁') ∈
              support (($ᵗ hashSpec.Range q) >>= fun w => pure (w, c₁.cacheQuery q w)) := by
            rw [hc₁] at hmem; exact hmem
          rw [mem_support_bind_iff] at hmem
          obtain ⟨x, hx, hxe⟩ := hmem
          simp only [support_pure, Set.mem_singleton_iff, Prod.mk.injEq] at hxe
          obtain ⟨hu, hc⟩ := hxe
          subst hu
          subst hc
          have hc₂ : c₂ q = none := by
            rcases hc : c₂ q with _ | w
            · rfl
            · rw [h hc] at hc₁; exact absurd hc₁ (by simp)
          refine ⟨c₂.cacheQuery q u, ?_, ?_⟩
          · intro t' u' ht'
            rcases eq_or_ne t' q with rfl | hne
            · rw [OracleSpec.QueryCache.cacheQuery_self] at ht'
              rw [OracleSpec.QueryCache.cacheQuery_self]
              exact ht'
            · rw [OracleSpec.QueryCache.cacheQuery_of_ne _ _ hne] at ht'
              rw [OracleSpec.QueryCache.cacheQuery_of_ne _ _ hne]
              exact h ht'
          · rw [hc₂]
            show (u, c₂.cacheQuery q u) ∈
              support (($ᵗ hashSpec.Range q) >>= fun w => pure (w, c₂.cacheQuery q w))
            rw [mem_support_bind_iff]
            exact ⟨u, mem_support_uniformSample _, by simp⟩

/-- Cache weakening for a whole computation, by induction on the free monad: every path of the
cached simulation from `c₁` is a path from any subcache `c₂`, with the same result. The starting
caches only have to be related, not equal, which is what makes the induction go through the
binds. -/
private theorem subcache_run {α : Type} (oa : OracleComp Spec α) :
    ∀ (c₁ c₂ : hashSpec.QueryCache), Subcache c₂ c₁ →
      ∀ (a : α) (c₁' : hashSpec.QueryCache),
        (a, c₁') ∈ support ((simulateQ oracleImpl oa).run c₁) →
        ∃ c₂', Subcache c₂' c₁' ∧ (a, c₂') ∈ support ((simulateQ oracleImpl oa).run c₂) := by
  induction oa using OracleComp.inductionOn with
  | pure x =>
      intro c₁ c₂ h a c₁' hmem
      simp only [simulateQ_pure, StateT.run_pure, support_pure, Set.mem_singleton_iff,
        Prod.mk.injEq] at hmem
      obtain ⟨rfl, rfl⟩ := hmem
      exact ⟨c₂, h, by simp⟩
  | query_bind t k ih =>
      intro c₁ c₂ h a c₁' hmem
      rw [simulateQ_query_bind, StateT.run_bind, mem_support_bind_iff] at hmem
      obtain ⟨⟨u, cmid⟩, hstep, hrest⟩ := hmem
      obtain ⟨cmid₂, hmid₂, hstep₂⟩ := subcache_step t c₁ c₂ h u cmid hstep
      obtain ⟨c₂', hle, hrest₂⟩ := ih u cmid cmid₂ hmid₂ a c₁' hrest
      refine ⟨c₂', hle, ?_⟩
      rw [simulateQ_query_bind, StateT.run_bind, mem_support_bind_iff]
      exact ⟨(u, cmid₂), hstep₂, hrest₂⟩

/-- Soundness against an oracle-adaptive prover: a prover that queries the oracle before
committing its memory is no stronger than one that commits first.

`Submission.Sound` quantifies the committed image `L` and the step count `n` plainly. This is
the general form, where both are produced by an arbitrary oracle computation `P` that may hash
first and choose its image from the answers. It follows from the plain form: a `true` path of the
adaptive experiment runs `P` from the empty cache to some `(L, n)` and some cache `c`, then runs
the machine and the verifier from `c`; cache weakening restricts that tail to a `true` path from
the empty cache, which `Sound` at that very `L` and `n` forbids. -/
theorem Submission.sound_adaptive (S : Submission) (sound : S.Sound)
    (pk : PublicKey) (m : Message) (σ : List Bool) (κ : ℕ)
    (hlo : minLogMem ≤ κ) (hhi : κ ≤ maxLogMem)
    (P : OracleComp Spec (MemImage κ × ℕ)) :
    probTrue (do
      let (L, n) ← P
      let outcome ← S.exec L n pk m σ
      let accepted ← S.scheme.verify pk m σ
      pure (outcome.isSome && !accepted)) = 0 := by
  rw [probTrue_eq_zero_iff]
  intro hmem
  rw [StateT.run'_eq, support_map] at hmem
  obtain ⟨⟨b, c⟩, hbc, hb⟩ := hmem
  simp only at hb
  subst hb
  rw [simulateQ_bind, StateT.run_bind, mem_support_bind_iff] at hbc
  obtain ⟨⟨⟨L, n⟩, cmid⟩, hP, hrest⟩ := hbc
  replace hrest : (true, c) ∈ support ((simulateQ oracleImpl (do
      let outcome ← S.exec L n pk m σ
      let accepted ← S.scheme.verify pk m σ
      pure (outcome.isSome && !accepted))).run cmid) := hrest
  obtain ⟨c₂', -, hfinal⟩ :=
    subcache_run _ cmid ∅ (fun t u hu => absurd hu (by simp)) true c hrest
  exact (probTrue_eq_zero_iff _).mp (sound pk m σ κ hlo hhi L n)
    (by rw [StateT.run'_eq, support_map]; exact ⟨(true, c₂'), hfinal, rfl⟩)

/-! ### The positive direction

`Submission.cyclesAtMost_of_no_completion` and `Submission.sound_of_never_completes` show that
each clause is vacuous on a bytecode nothing completes. This is the converse: on a submission
whose honest run does complete, `CyclesAtMost` is a bound on something. The step between the two
oracle semantics is `OracleComp.support_simulateQ_run'_subset`, `VCVio`'s statement that
simulating a computation only shrinks its support. -/

/-- Every result the cached simulation can produce is a result the computation can produce:
the cache restricts which answer sequences are coherent, it never adds a path. This is the
bridge from the `probTrue` clauses (`Faithful`, `Sound`) to the `support` clause
(`CyclesAtMost`).

`OracleComp.support_simulateQ_run'_subset` is this statement for `run'`; discarding the final
cache here is the same `Prod.fst`. -/
theorem mem_support_of_mem_support_run {α : Type} (oa : OracleComp Spec α) (a : α)
    (c₀ c : hashSpec.QueryCache) (h : (a, c) ∈ support ((simulateQ oracleImpl oa).run c₀)) :
    a ∈ support oa := by
  refine support_simulateQ_run'_subset oracleImpl oa c₀ ?_
  rw [StateT.run'_eq, support_map]
  exact ⟨(a, c), h, rfl⟩

/-- `Faithful` makes `CyclesAtMost` bite. If the honest prover's run completes on some input
along some coherent oracle path, then that completion is also a path of the `support` clause,
so the claim is at least the public-boundary surcharge every submission carries. A bytecode no
image completes escapes this only by failing `Faithful` against `Admissible.correct`.

The hypothesis is exactly "the honest run completes somewhere": `probTrue (S.honestRun pk m σ)`
is nonzero. `Faithful` supplies the two memory-size bounds `CyclesAtMost` asks for, and the
honest image and step count instantiate its plain quantifiers. -/
theorem Submission.boundaryCycles_le (S : Submission) (c : ℕ)
    (faithful : S.Faithful) (cycles : S.CyclesAtMost c)
    (pk : PublicKey) (m : Message) (σ : List Bool)
    (h : probTrue (S.honestRun pk m σ) ≠ 0) :
    boundaryCycles ≤ c := by
  rw [Ne, probTrue_eq_zero_iff, not_not] at h
  rw [StateT.run'_eq, support_map] at h
  obtain ⟨⟨b, cend⟩, hbc, hb⟩ := h
  simp only at hb
  subst hb
  rw [Submission.honestRun, simulateQ_bind, StateT.run_bind, mem_support_bind_iff] at hbc
  obtain ⟨⟨L, cmid⟩, -, hrest⟩ := hbc
  simp only at hrest
  rw [simulateQ_map, StateT.run_map, support_map] at hrest
  obtain ⟨⟨outcome, cfin⟩, hout, heq⟩ := hrest
  simp only [Prod.mk.injEq] at heq
  obtain ⟨hsome, -⟩ := heq
  obtain ⟨cost, rfl⟩ := Option.isSome_iff_exists.mp hsome
  have hmem := mem_support_of_mem_support_run _ _ cmid cfin hout
  have hle := cycles pk m σ S.memLog faithful.1 faithful.2.1 L (S.steps pk m σ) cost hmem
  omega

end OptimalOTS.LeanIsa

/-! ## 10. Axiom audit of the derived facts

`scripts/check-axioms.lean` audits the protected contract; these guard the theorems this file
adds on top of it. -/

/--
info: 'OptimalOTS.LeanIsa.probTrue_eq_zero_iff' depends on axioms: [propext, Classical.choice, Quot.sound]
-/
#guard_msgs in
#print axioms OptimalOTS.LeanIsa.probTrue_eq_zero_iff

/--
info: 'OptimalOTS.LeanIsa.Submission.cyclesAtMost_of_no_completion' depends on axioms: [propext, Classical.choice, Quot.sound]
-/
#guard_msgs in
#print axioms OptimalOTS.LeanIsa.Submission.cyclesAtMost_of_no_completion

/--
info: 'OptimalOTS.LeanIsa.Submission.sound_of_never_completes' depends on axioms: [propext, Classical.choice, Quot.sound]
-/
#guard_msgs in
#print axioms OptimalOTS.LeanIsa.Submission.sound_of_never_completes

/--
info: 'OptimalOTS.LeanIsa.Submission.sound_adaptive' depends on axioms: [propext, Classical.choice, Quot.sound]
-/
#guard_msgs in
#print axioms OptimalOTS.LeanIsa.Submission.sound_adaptive

/--
info: 'OptimalOTS.LeanIsa.mem_support_of_mem_support_run' depends on axioms: [propext, Classical.choice, Quot.sound]
-/
#guard_msgs in
#print axioms OptimalOTS.LeanIsa.mem_support_of_mem_support_run

/--
info: 'OptimalOTS.LeanIsa.Submission.boundaryCycles_le' depends on axioms: [propext, Classical.choice, Quot.sound]
-/
#guard_msgs in
#print axioms OptimalOTS.LeanIsa.Submission.boundaryCycles_le
