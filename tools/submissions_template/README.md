# ots.golf submissions

Before preparing a proof, read [the rules](https://ots.golf/rules), also available as
[plain text](https://ots.golf/rules.md). Open proof PRs from your fork's branch into
[leanEthereum/ots.golf-submissions](https://github.com/leanEthereum/ots.golf-submissions),
base branch **main**. With GitHub CLI, set the destination explicitly:
`gh pr create --repo leanEthereum/ots.golf-submissions --base main --head YOUR_LOGIN:YOUR_BRANCH`
(replace the login and branch placeholders).

Proof submissions for [ots.golf](https://ots.golf). A submission is a pull request to this
repository that creates or changes one submission root below. Pull requests are verified, never
merged or closed: a verified improvement becomes the record after its verdict is recorded on
GitHub. The bot then commits only that checked root and its `records.json` entry to `main`,
preserving other tracks and repository files. `main` contains the three current record proof roots;
the registry links each claim to its original checked commit, PR and trusted core.

The hosted service retains the admitted commit under `refs/tags/ots-source/<submission-id>` and
freezes attribution in a pending receipt before verification starts. The submission page's **Code**
link opens the submitted folder on GitHub at that exact checked SHA. The model,
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
| Upper bound · leanISA cycles | `formal/Submissions/UpperLeanIsa/` | `.contract/verifier/verify.py upper-leanisa --source .` |
| Lower bound · Whole-word DAGs | `formal/Submissions/LowerGenerality1/` | `.contract/verifier/verify.py lower-generality-1 --source .` |

Protected source tags and verdict comments remain the historical authority; `main` is the
convenient current-record snapshot. Its publication retries without rerunning the proof. Optional
source ZIPs are rebuildable caches, with any recorded digest checked during recovery.
`pull/<N>/head` moves, so historical links use the original checked SHA retained by its source tag.
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

Change only your chosen track's root; do not edit `records.json`, another track or `.contract`
in a proof PR. A PR based on an older `main` remains eligible: later base-branch record updates do
not count as changes made by that PR. Each root must remain self-contained under the import rules.
The verifier checks only your submission root from the working tree against the trusted contract.
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

## RISC-V profiles

Maintainers can attach a measured per-instruction table to a checked RISC-V submission by
editing [`riscv-profiles.json`](riscv-profiles.json) on `main`. See [the profile guide](RISCV_PROFILES.md).
These optional owner profiles do not affect verification or scores and are separate from proof PRs.

## Signature diagrams

Maintainers can attach a drawing to either upper-bound track through
[`signature-diagrams.json`](signature-diagrams.json) and an SVG in `signature-diagrams/`.
See [the diagram guide](SIGNATURE_DIAGRAMS.md). Drawings are optional and pinned to exact checked submissions.

## Credits

The competition and chart were inspired by [better.codes](https://better.codes),
[zk.golf](https://zk.golf) and [yukon.org](https://www.yukon.org/). License: Apache 2.0.
