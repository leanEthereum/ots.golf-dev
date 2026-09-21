import Lake
open Lake DSL

package OptimalOTS where
  leanOptions := #[
    ⟨`pp.unicode.fun, true⟩,
    ⟨`autoImplicit, false⟩,
    ⟨`relaxedAutoImplicit, false⟩
  ]

require VCVio from git
  "https://github.com/Verified-zkEVM/VCVio" @ "25f26bfee60d6700644eb1a69f091091948f15da"

require «riscv-zkvm» from git
  "https://github.com/Verified-zkEVM/riscv-zkvm" @ "4634e41b229da4256e4a1f1688b94133fffa4af0"

require leanerVM from git
  "https://github.com/Verified-zkEVM/leanerVM" @ "8563b05b03434851badc19715f6162fb70ffc093"

-- `cslib` and `PolyFun` are shared, transitive, and reachable from both VCVio and leanerVM's
-- dependency tree, so adding leanerVM lets Lake re-resolve them. It does: cslib moves to the
-- `v4.33.1` tag, where `FreeM.lift_bind` no longer exists as a theorem, and
-- `VCVio.EvalDist.PFunctor` stops compiling. Declaring them at the root pins the revisions the
-- VCVio pin above was built against. Nothing in the leanISA import closure
-- (`LeanerVM.Parameters.*`, `LeanerVM.Semantics.*`) uses either package.
require cslib from git
  "https://github.com/dtumad/cslib.git" @ "268b2bb36c7ac161f3a95f97d5946097befcfdd1"

require PolyFun from git
  "https://github.com/Verified-zkEVM/PolyFun.git" @ "2348446013d72990237232444e656955f85f97c9"

/-- Contract definitions, derived results, and rendered challenge stubs. -/
@[default_target] lean_lib OptimalOTS where
  globs := #[.submodules `OptimalOTS]

/-- A submission may add or edit only the root assigned to its track in `challenges.json`. -/
lean_lib Submissions where
  globs := #[.submodules `Submissions]

/-- Internal checks: the whole-word lower-bound class is not empty, and numeric
checks of the DAG constants. -/
lean_lib Witnesses where
  globs := #[.submodules `Witnesses]
