# Documentation

Proof guides and reviews for ots.golf. The rules are on [ots.golf/rules](https://ots.golf/rules);
the precise submission specification is [AGENTS.md](../AGENTS.md). The proofs described here are
submission roots in the submissions repository, not in this core.

## Proof guides

| Guide | Track |
|---|---|
| [upper-compressions.md](upper-compressions.md) | Upper bound: the forest construction and its certificate |
| [upper-bound-proof.md](upper-bound-proof.md) | Upper bound: architecture of the forest's security proof |
| [upper-riscv.md](upper-riscv.md) | RISC-V upper bound: machine ABI and certificate |
| [upper-leanisa.md](upper-leanisa.md) | leanISA upper bound: committed memory, certificate and model boundaries |
| [upper-riscv-hint.md](upper-riscv-hint.md) | Hinted RISC-V upper bound: prover-chosen views, the two-clause certificate and where strong unforgeability lives |
| [lower-generality-1.md](lower-generality-1.md) | Whole-word DAGs lower bound: the whole-word class and its proof |

## Reviews and setup

- [AUDIT.md](AUDIT.md): audit of the contract semantics and trusted components.
- [repositories.md](repositories.md): the core and submissions repositories, and workspace preparation.
