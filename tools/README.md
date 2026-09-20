# Tools

Numerical research scripts, the repository regression runner, and the submissions-repository
preparation script. Numerical results are exploration only: every claim requires a Lean proof.

| Script | Purpose |
|---|---|
| `tune_lower_bound.py` | exact attack arithmetic for the lower bounds |
| `search_forest.py` | search for forest constructions (needs NumPy) |
| `literature_chain_baseline.py` | reproduce the chart's equal-chain comparison with exact integers |
| `check_repo.py` | repository regression checks |
| `prepare_submissions_repo.py` | create a new, empty submissions repository pinned to this core |

## Numerical tools

`python3 tools/literature_chain_baseline.py` reproduces the **105-compression** equal-chain
baseline. It retains the reference nonce-grinding encoding and searches chain counts and
lengths under the model's resource limits. See [the derivation](../docs/literature-baseline.md)
for the paper attribution, assumptions and cost breakdown. It needs only the standard library.

`tune_lower_bound.py` uses exact integers and fractions. Its exact modes use `2^20` signing
trials and the reciprocal success lower bound `128/129`, matching the current DAG contract
and proofs:

```sh
python3 tools/tune_lower_bound.py --method words --claims 90,91     # whole-word attack
python3 tools/tune_lower_bound.py --method patterns --claims 18     # unrestricted DAG certificate
python3 tools/tune_lower_bound.py --method disclosure --claims 80   # historical bounded-origin estimate
```

The entropy mode is conditional research; its missing hypotheses are false in the bare model.

`search_forest.py` needs NumPy, kept out of the service dependencies in an isolated environment:

```sh
uv venv .venv-tools
uv pip install --python .venv-tools/bin/python numpy
.venv-tools/bin/python tools/search_forest.py --check 14,3,3,7 --overhead 16
.venv-tools/bin/python -m unittest discover -s tools/tests -v
```

The checked shape has key-generation cost 912 and reconstruction cost 105, plus one compression
for the message-and-nonce index. `--overhead` adds explicit bits to each graph hash input only; it
never changes the index query. Float arithmetic finds candidates; Python integers recount the
selected disclosure family exactly.

## Repository checks

After preparing the service environment:

```sh
python3 tools/check_repo.py --numerics-python .venv-tools/bin/python --formal --paper
```

- `--formal` builds the contract, audits its axioms and builds the internal lower-bound witnesses
  (`lake build Witnesses`).
- `--paper` compiles the paper with latexmk.
- `--official --submissions PATH` runs the official pipeline for every track whose root exists in
  that submissions checkout.
- `--node /path/to/node` overrides the Node.js used for static JavaScript syntax checks.

The runner uses the existing warm Lean and tool caches; it never installs packages, refreshes
demos, pushes or deploys. Browser checks use `service/browser_check.py` against the seeded local
preview. Linux sandbox acceptance runs on the deployment host with
`verifier/check_linux_sandbox.py`; a macOS pass cannot replace it.

## Submissions repository

```sh
python3 tools/prepare_submissions_repo.py .build/ots.golf-submissions
```

Creates a new local repository with no submission roots: the README, agent instructions and PR
template from [`submissions_template/`](submissions_template/), and a `.contract` submodule pinned
to this commit. It requires a clean, committed core checkout and a new destination, and never
pushes. See [repository setup](../docs/repositories.md).
