import OptimalOTS.Model

/-!
# The DAG signature contract

A scheme is a public computation graph with secret sources, deterministic nodes and hash nodes.
A signature is a nonce and a cut of the graph; verification reconstructs the root and checks its
public-key bits. The oracle, the costs and the budgets are those of `Model.lean`; deterministic
computation is free. The lower-bound statement is `LowerBoundGenerality2`.
-/

open OracleSpec OracleComp ENNReal

noncomputable section

open scoped Classical

namespace OptimalOTS.Dag

/-! ## 1. The signature format

A signature is a nonce `η` and the values of the cut `sets i`, where `i` is the low `idxBits`
bits of `H(m ‖ η)`. An index is valid when it is below `numCuts`; the signer tries fresh nonces
until one gives a valid index, at most `trials` times. -/

/-- Length of signing nonces. -/
def nonceBits : ℕ := 128

/-- Width of the disclosure index, the low bits of `H(m ‖ η)`. A trial finds a valid index with
probability `numCuts / 2 ^ idxBits = 2 ^ -13`. -/
def idxBits : ℕ := 128

/-- Cost of the index query `H(m ‖ η)`. -/
def idxCost : ℕ := blockCost (msgBits + nonceBits)

/-- Maximal number of nonces tried by the signer: as many index queries as the signing budget
pays for. -/
def trials : ℕ := signBudget / idxCost

/-- Number of cuts, i.e. of valid indices: the smallest power of two for which all `trials`
trials fail with probability at most `1 / 2 ^ signingFailureBits`. Here that probability is
`(1 - 2 ^ -13) ^ (2 ^ 20) < 2 ^ -184`; with `2 ^ 114` cuts it would exceed `2 ^ -93`. -/
def numCuts : ℕ := 2 ^ 115

abbrev Nonce := BitVec nonceBits
/-- A signature: a nonce and the revealed bits. -/
abbrev Signature := Nonce × List Bool

/-! ## 2. Computation graphs -/

/-- The kind of node `v` in a graph with `N` nodes and output lengths `len`. Parents precede their
children, so the order of `Fin N` is a topological order. -/
inductive NodeKind (N : ℕ) (len : Fin N → ℕ) (v : Fin N) : Type where
  /-- A secret source: a uniformly random string. -/
  | source
  /-- A deterministic node: any public function of its parents' values. The function receives
  all node values but may only depend on those of its parents. -/
  | det (parents : Finset (Fin N)) (parents_lt : ∀ w ∈ parents, w < v)
      (f : ((w : Fin N) → BitVec (len w)) → BitVec (len v))
      (f_local : ∀ x y : (w : Fin N) → BitVec (len w),
        (∀ w ∈ parents, x w = y w) → f x = f y)
  /-- A hash node: the random oracle on its parent's value. -/
  | hash (parent : Fin N) (parent_lt : parent < v) (len_eq : len v = hashBits)

namespace NodeKind

variable {N : ℕ} {len : Fin N → ℕ} {v : Fin N}

/-- The parents of a node. -/
def parents : NodeKind N len v → Finset (Fin N)
  | source => ∅
  | det ps _ _ _ => ps
  | hash p _ _ => {p}

/-- The node is a secret source. -/
def IsSource : NodeKind N len v → Prop
  | source => True
  | _ => False

/-- The node is a hash node. -/
def IsHash : NodeKind N len v → Prop
  | hash .. => True
  | _ => False

end NodeKind

/-- A public computation graph. -/
structure Graph where
  /-- Number of nodes. -/
  size : ℕ
  /-- Output length of each node. -/
  len : Fin size → ℕ
  /-- The kind of each node. -/
  kind : (v : Fin size) → NodeKind size len v
  /-- The root; its value is resized to `pkBits` to obtain the public key (the low bits). -/
  root : Fin size
  root_isHash : (kind root).IsHash

namespace Graph

variable (G : Graph)

/-- A value for every node. -/
abbrev Assignment := (v : Fin G.size) → BitVec (G.len v)

/-- Query cost of evaluating node `v`: the block cost of its input for a hash node, else zero. -/
def nodeCost (v : Fin G.size) : ℕ :=
  match G.kind v with
  | .hash p _ _ => blockCost (G.len p)
  | _ => 0

/-- Query cost of key generation, which evaluates every node once. -/
def keygenCost : ℕ := ∑ v, G.nodeCost v

/-- The nodes reached by walking backwards from the root, stopping at the nodes of `A`. -/
inductive Visited (A : Finset (Fin G.size)) : Fin G.size → Prop
  | root : Visited A G.root
  | parent {w v : Fin G.size} : Visited A w → w ∉ A → v ∈ (G.kind w).parents → Visited A v

/-- The nodes evaluated when reconstructing the root from the values on `A`. -/
def evaluated (A : Finset (Fin G.size)) : Finset (Fin G.size) :=
  Finset.univ.filter fun v => G.Visited A v ∧ v ∉ A

/-- Query cost of reconstructing the root from the values on `A`. -/
def reconstructCost (A : Finset (Fin G.size)) : ℕ := ∑ v ∈ G.evaluated A, G.nodeCost v

/-- Number of bits of the values on `A`. -/
def revealBits (A : Finset (Fin G.size)) : ℕ := ∑ v ∈ A, G.len v

/-- Compute node `v` from the values `x` of earlier nodes; `onSource` gives a source's value. -/
def evalNode (x : G.Assignment) (v : Fin G.size)
    (onSource : OracleComp Spec (BitVec (G.len v))) :
    OracleComp Spec (BitVec (G.len v)) :=
  match G.kind v with
  | .source => onSource
  | .det _ _ f _ => pure (f x)
  | .hash p _ h => (fun y => y.cast h.symm) <$> hash (x p)

/-- Sample a uniform value for every node (only the sources' values are used). -/
def sampleAssignment : OracleComp Spec G.Assignment :=
  (List.finRange G.size).foldlM
    (fun z v => Function.update z v <$> sampleBits (G.len v))
    (fun _ => 0)

/-- Evaluate every node in order; a source takes its value from `z`. -/
def evaluate (z : G.Assignment) : OracleComp Spec G.Assignment :=
  (List.finRange G.size).foldlM
    (fun x v => Function.update x v <$> G.evalNode x v (pure (z v)))
    (fun _ => 0)

/-- Key generation: sample the sources, then evaluate every node. -/
def keygen : OracleComp Spec G.Assignment := do
  let z ← G.sampleAssignment
  G.evaluate z

/-- Root reconstruction: take the given values on `A`, evaluate the other visited nodes, and set
the remaining nodes to zero. -/
def reconstruct (A : Finset (Fin G.size)) (given : G.Assignment) :
    OracleComp Spec G.Assignment :=
  (List.finRange G.size).foldlM
    (fun x v => do
      if v ∈ A then
        return Function.update x v (given v)
      else if G.Visited A v then
        Function.update x v <$> G.evalNode x v (pure 0)
      else
        return Function.update x v 0)
    (fun _ => 0)

/-- The revealed bit string: the values on `A`, in node order. -/
def encode (A : Finset (Fin G.size)) (x : G.Assignment) : List Bool :=
  ((List.finRange G.size).filter fun v => decide (v ∈ A)).flatMap fun v => toBits (x v)

/-- Position of the value of `v` in `encode A`. -/
def offset (A : Finset (Fin G.size)) (v : Fin G.size) : ℕ :=
  ∑ w ∈ A.filter (· < v), G.len w

/-- Read each node's value at its offset in the disclosure string. Reconstruction uses these
values only on `A`; values outside `A` need not have a meaningful decoding. -/
def decode (A : Finset (Fin G.size)) (l : List Bool) : G.Assignment :=
  fun v => ofBits (G.len v) ((l.drop (G.offset A v)).take (G.len v))

end Graph

/-! ## 3. Schemes -/

/-- A graph-based one-time signature scheme. -/
structure Scheme where
  /-- The public computation. -/
  graph : Graph
  /-- The disclosure sets. -/
  sets : Fin numCuts → Finset (Fin graph.size)
  /-- The verifier must recompute the root. -/
  root_not_mem : ∀ i, graph.root ∉ sets i
  /-- The revealed values suffice: `sets i` meets every path from a secret source to the root. -/
  no_hidden_source :
    ∀ i v, graph.Visited (sets i) v → v ∉ sets i → ¬ (graph.kind v).IsSource
  /-- A signature, nonce included, has at most `maxSignatureBits` bits. -/
  reveal_le : ∀ i, graph.revealBits (sets i) + nonceBits ≤ maxSignatureBits
  /-- Key generation costs at most `keygenBudget`. -/
  keygen_le : graph.keygenCost ≤ keygenBudget

/-- The disclosure index selected by message `m` and nonce `η`. The index query shares the one
oracle with the graph's hash nodes: equal inputs get equal answers. -/
def index (m : Message) (η : Nonce) : OracleComp Spec ℕ :=
  (fun y => (y.setWidth idxBits).toNat) <$> hash (m ++ η)

namespace Scheme

variable (S : Scheme)

/-- Resize the root value to `pkBits`: truncation keeps the low bits; extension pads with zeros. -/
def publicKey (x : S.graph.Assignment) : PublicKey := (x S.graph.root).setWidth pkBits

/-- Key generation; the secret key is the value of every node. -/
def keygen : OracleComp Spec (PublicKey × S.graph.Assignment) := do
  let x ← S.graph.keygen
  return (S.publicKey x, x)

/-- Signing with at most `k` further trials, never retrying a nonce in `tried`. -/
def signLoop (x : S.graph.Assignment) (m : Message) :
    ℕ → Finset Nonce → OracleComp Spec (Option Signature)
  | 0, _ => pure none
  | k + 1, tried =>
    let fresh := Finset.univ \ tried
    if h : 0 < fresh.card then do
      let j ← (liftM ($[0..(fresh.card - 1)]) : OracleComp Spec (Fin (fresh.card - 1 + 1)))
      let η : Nonce := (fresh.equivFin.symm (Fin.cast (by omega) j)).1
      let i ← index m η
      if hi : i < numCuts then
        return some (η, S.graph.encode (S.sets ⟨i, hi⟩) x)
      else
        signLoop x m k (insert η tried)
    else
      pure none

/-- Try at most `trials` distinct uniform nonces; return `none` if none selects a valid index. -/
def sign (x : S.graph.Assignment) (m : Message) : OracleComp Spec (Option Signature) :=
  S.signLoop x m trials ∅

/-- Reject invalid indices or payload lengths; otherwise reconstruct the root and compare its
public-key bits with `pk`. -/
def verify (pk : PublicKey) (m : Message) (σ : Signature) : OracleComp Spec Bool := do
  let i ← index m σ.1
  if hi : i < numCuts then
    let A := S.sets ⟨i, hi⟩
    if σ.2.length = S.graph.revealBits A then
      let y ← S.graph.reconstruct A (S.graph.decode A σ.2)
      return decide (S.publicKey y = pk)
    else
      return false
  else
    return false

/-- Verification cost at a valid index and payload length: the index query plus reconstruction.
The cost depends on the disclosure set, not on the supplied values or the final verdict. -/
def verifyCost (i : Fin numCuts) : ℕ := idxCost + S.graph.reconstructCost (S.sets i)

end Scheme

/-! ## 4. Security -/

/-- A one-signature attacker. It may use the random oracle and free randomness throughout. -/
structure Adversary where
  /-- State passed between the two stages. -/
  State : Type
  /-- Given the public key, choose the message to be signed. -/
  choose : PublicKey → OracleComp Spec (Message × State)
  /-- Given the signature (`none` if signing failed), output a forgery. -/
  forge : State → Option Signature → OracleComp Spec (Message × Signature)

/-- Strong-forgery experiment. The attacker wins when its pair is accepted and differs from the
signed pair; after signing failure, any accepted pair wins. All parties share one oracle table. -/
def experiment (S : Scheme) (A : Adversary) : OracleComp Spec Bool := do
  let (pk, sk) ← S.keygen
  let (m₁, st) ← A.choose pk
  let σ₁ ← S.sign sk m₁
  let (m₂, σ₂) ← A.forge st σ₁
  let ok ← S.verify pk m₂ σ₂
  return ok && decide (σ₁.map (fun s => (m₁, s)) ≠ some (m₂, σ₂))

/-- Strong unforgeability: for every attacker and pathwise budget `B` for the entire experiment,
the probability of an accepted fresh pair is strictly below `B / 2 ^ securityBits`. -/
def Scheme.Secure (S : Scheme) : Prop :=
  ∀ (A : Adversary) (B : ℕ), CostAtMost (experiment S A) B →
    probTrue (experiment S A) < (B : ℝ≥0∞) / 2 ^ securityBits

end OptimalOTS.Dag

namespace OptimalOTS

open Dag

/-! ## 5. The lower bound -/

/-- Generality 2/3: every secure DAG scheme has a signature index whose verification costs at
least `c` compressions. -/
def LowerBoundGenerality2 (c : ℕ) : Prop :=
  ∀ S : Scheme, S.Secure → ∃ i : Fin numCuts, c ≤ S.verifyCost i

end OptimalOTS
