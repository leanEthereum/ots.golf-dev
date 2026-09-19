# ots.golf

How cheaply can a hash-based one-time signature be verified?

[ots.golf](https://ots.golf) is a competition in which every claim is a Lean proof about a pinned
contract. This repository, **ots.golf-dev**, is the core: the Lean model, the verifier and the
website. It holds no track proofs; those are submitted as pull requests to
[ots.golf-submissions](https://github.com/leanEthereum/ots.golf-submissions).

**Rules:** read them on [ots.golf/rules](https://ots.golf/rules). [AGENTS.md](AGENTS.md) is the
precise specification: exact exports, submission-root rules, limits and the submission workflow.

## Tracks

| Track | Folder | Check it with |
|---|---|---|
| Upper bound · compressions | `formal/Submissions/UpperCompressions/` | `verify.py upper-compressions` |
| Upper bound · RISC-V cycles | `formal/Submissions/UpperRiscv/` | `verify.py upper-riscv` |
| Lower bound · Generality 1/3 | `formal/Submissions/LowerGenerality1/` | `verify.py lower-generality-1` |
| Lower bound · Generality 2/3 | `formal/Submissions/LowerGenerality2/` | `verify.py lower-generality-2` |
| Lower bound · Generality 3/3 | `formal/Submissions/LowerGenerality3/` | `verify.py lower-generality-3` |

Roots live at `formal/Submissions/<Root>/` in the submissions repository. Current records are
on [ots.golf](https://ots.golf).

## Quick start

Build the contract and check a submission root from a submissions checkout next to this one:

```sh
verifier/setup_tools.sh
(cd formal && lake exe cache get && lake build OptimalOTS && lake env lean scripts/check-axioms.lean)
python3 verifier/verify.py lower-generality-1 --source ../ots.golf-submissions
```

`verify.py` takes only the track's root from `--source`; the contract and tooling come from this
checkout. macOS verification runs unsandboxed, for trusted local development; hosted verification
requires the Linux isolation in the [deployment guide](service/deploy/README.md).

Run the website locally with the committed [demo fixtures](service/demo/README.md):

```sh
cd service
uv sync --frozen
./run-local.sh        # http://localhost:8000
```

## Repository map

| Path | Contents |
|---|---|
| [`AGENTS.md`](AGENTS.md) | submission specification |
| [`challenges.json`](challenges.json) | track metadata, limits, protected files |
| [`formal/OptimalOTS/`](formal/OptimalOTS/) | the contract: [`Model.lean`](formal/OptimalOTS/Model.lean), [`Dag.lean`](formal/OptimalOTS/Dag.lean), [`WholeWords.lean`](formal/OptimalOTS/WholeWords.lean), [`OracleAlgorithm.lean`](formal/OptimalOTS/OracleAlgorithm.lean), [`Riscv.lean`](formal/OptimalOTS/Riscv.lean), [`RiscvMachine.lean`](formal/OptimalOTS/RiscvMachine.lean), and the challenge stubs in `Challenge/` |
| `formal/Witnesses/` | internal maintainer check that the Generality 1/3 and 2/3 classes are non-empty (`lake build Witnesses`); not a track |
| [`verifier/`](verifier/) | [`verify.py`](verifier/verify.py), policy checks, contract pin, comparator configs |
| [`service/`](service/README.md) | website and hosted verifier; [deployment](service/deploy/README.md) |
| [`docs/`](docs/README.md) | proof guides, contract audit, repository setup |
| [`tools/`](tools/README.md) | numerical research tools, repository checks, submissions-repo preparation |
| `paper/` | the paper on the unrestricted DAG bound |

See [repository setup](docs/repositories.md) for how the core and submissions repositories fit
together.

## Credits

The competition and chart were inspired by [better.codes](https://better.codes),
[zk.golf](https://zk.golf) and [yukon.org](https://www.yukon.org/). License: Apache 2.0.
