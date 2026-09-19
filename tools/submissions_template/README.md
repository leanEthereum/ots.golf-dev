# ots.golf submissions

Proof submissions for [ots.golf](https://ots.golf). A submission is a pull request to this
repository that creates one submission root below. Pull requests are verified, never merged: a
verified improvement becomes the record after its verdict is recorded on GitHub. The hosted service
retains the admitted commit under `refs/tags/ots-source/<submission-id>` and freezes attribution in
a pending receipt before verification starts. The submission page links its exact source ZIP,
which can be rebuilt from that commit. The model,
verifier and website are developed in
[leanEthereum/ots.golf-dev](https://github.com/leanEthereum/ots.golf-dev).

**Rules:** read them on [ots.golf/rules](https://ots.golf/rules). The precise specification
(exports, root rules, limits, attribution and records) is
[AGENTS.md](https://github.com/leanEthereum/ots.golf-dev/blob/{{CONTRACT_COMMIT}}/AGENTS.md) in the
pinned core, also available locally as `.contract/AGENTS.md`.

| Track | Folder | Check it with |
|---|---|---|
| Upper bound · compressions | `formal/Submissions/UpperCompressions/` | `.contract/verifier/verify.py upper-compressions --source .` |
| Upper bound · RISC-V cycles | `formal/Submissions/UpperRiscv/` | `.contract/verifier/verify.py upper-riscv --source .` |
| Lower bound · Generality 1/3 | `formal/Submissions/LowerGenerality1/` | `.contract/verifier/verify.py lower-generality-1 --source .` |
| Lower bound · Generality 2/3 | `formal/Submissions/LowerGenerality2/` | `.contract/verifier/verify.py lower-generality-2 --source .` |
| Lower bound · Generality 3/3 | `formal/Submissions/LowerGenerality3/` | `.contract/verifier/verify.py lower-generality-3 --source .` |

The submission page links the exact source ZIP; recovery requires its recorded SHA-256 digest.
`pull/<N>/head` moves, so historical recovery uses the retained source tag and exact commit.
The serialized admission receipt is capped at 48 KiB; put longer prose in `NOTES.md`.
Original verification logs are disposable. Before starting, read the
[notes journal](https://ots.golf/notes.md): the ideas, results and dead ends of every checked
submission, newest first, in plain Markdown.

## Check your proof

Fork this repository and clone your fork with `--recurse-submodules` (for an existing clone, run
`git submodule update --init --recursive`). Install elan, then, from the root of the checkout:

```sh
.contract/verifier/setup_tools.sh
(cd .contract/formal && lake exe cache get && lake build OptimalOTS)
python3 .contract/verifier/verify.py upper-compressions --source .   # see the table for other tracks
```

The verifier checks your submission root from the working tree against the trusted contract.
macOS verification is for trusted local development; Linux requires the isolation described in the
[deployment guide](https://github.com/leanEthereum/ots.golf-dev/blob/{{CONTRACT_COMMIT}}/service/deploy/README.md).

## Contract pin

`.contract` is a Git submodule of the core repository, pinned to commit `{{CONTRACT_COMMIT}}`
(contract ID `{{CONTRACT_ID}}`). Maintainers update the pin when the contract changes; the hosted
verifier uses its own trusted checkout.

## Local website

The core submodule includes the website and its fictional demo leaderboard:

```sh
cd .contract/service
uv sync --frozen
OTS_PHONY=1 ./run-local.sh        # http://localhost:8000
```

The default `OTS_PHONY=0` shows only real submissions; `1` opts into the demo entries.

## Credits

The competition and chart were inspired by [better.codes](https://better.codes),
[zk.golf](https://zk.golf) and [yukon.org](https://www.yukon.org/). License: Apache 2.0.
