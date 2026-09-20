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
