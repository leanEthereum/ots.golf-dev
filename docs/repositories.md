# Core and submissions repositories

| Repository | Contents and role |
|---|---|
| [ots.golf-dev](https://github.com/leanEthereum/ots.golf-dev) | Trusted Lean model, challenge stubs, verifier, website and tooling; no track proofs |
| [ots.golf-submissions](https://github.com/leanEthereum/ots.golf-submissions) | Proof PRs; `main` holds five current record roots, `records.json`, contributor files and the pinned core submodule |

The local workspace contains both repositories:

```text
sig.golf/
├── ots.golf-dev/
└── ots.golf-submissions/
```

Run core commands from `ots.golf-dev/` and submission checks from `ots.golf-submissions/`.
The maintenance workflow is commit, push, then update the live `h2` deployment; no localhost is
required. For explicitly requested local development, `bash service/run-local.sh` starts a preview.
The [committed demo fixtures](../service/demo/submissions.json) populate a local database when
`OTS_PHONY=1`; the default is `OTS_PHONY=0`. They belong to the website in the core repository; checked proof submissions
belong to `ots.golf-submissions`.

The submissions workspace has a `.contract` submodule pinned to a core commit for local proof
checking. Its PRs create or change one admitted root. A PR based on an older `main` remains
eligible: later record updates on the base branch are not changes made by the PR. Do not edit
`records.json`, another track or `.contract` in a proof PR. The hosted verifier reads only the
admitted root from the exact PR head, using its trusted core for protected files and tooling.

Verification results are reported to the PR in the submissions repository as a commit status and
a comment. A verified improvement becomes the record: the first verified head whose claim strictly
improves the track's record when its verification finishes; on a track without a record, the first
verified head. A result becomes public as verified after its verdict comment is durable. Pull
requests are never merged. The service retains the exact admitted commit in the base submissions
repository under `refs/tags/ots-source/<submission-id>` and freezes attribution in a pending receipt
before the worker can start. The submission page's Code link opens that root on GitHub at its
original checked SHA. Optional source ZIPs are rebuildable caches; GitHub tags and receipt/verdict
comments are durable state. No server backups are required,
and lost original logs remain unavailable. `pull/<N>/head` moves and is not a historical archive.

After a new record's verdict is durable, the bot makes a separate commit to submissions `main`,
copying only that checked root and updating its `records.json` entry. The registry links the track
and claim to the original source commit, PR and trusted core. Other tracks and repository files
are preserved. The bot remains the commit author and adds every Git author and co-author of the
admitted PR commits as `Co-authored-by` trailers, deduplicated by email. Admission freezes these
identities in the durable receipt; GitHub-only recovery preserves them even if the PR head moves.
This current-record snapshot is convenient to clone; protected source tags and
verdict comments remain the historical authority. Failed snapshot writes retry through the outbox
without rechecking the proof. Submissions never change the model, website, or trusted checkout. Repository
identity is retained in each PR URL, so moving intake does not send old result comments to an
unrelated PR with the same number.

## Prepare the submissions repository

Commit and check the core changes, then run:

```sh
python3 tools/prepare_submissions_repo.py .build/ots.golf-submissions
```

The destination must be new. The command bootstraps contributor files and the pinned core
submodule; it does not copy proof roots or invent records. Checked records subsequently populate
`main` and `records.json`. The initial five verified records may be seeded by a maintainer from
their exact checked roots; every future new verified record is committed automatically by the bot.
Its `origin` points to `leanEthereum/ots.golf-submissions`.
It uses the local core checkout and does not contact GitHub or push anything.

Review and commit the prepared files. Publish the pinned core commit before publishing this
repository, so contributors can obtain the submodule. Contributors fork the submissions repository,
clone with `--recurse-submodules`, and follow its README for tool setup and local verification.

To update an existing competition contract, first deploy the reviewed core and then update the
submodule pin in a maintainer PR. The preparation command never overwrites an existing repository.

## Service configuration

```sh
OTS_CONTRACT_REPO=leanEthereum/ots.golf-dev
OTS_SUBMISSIONS_REPO=leanEthereum/ots.golf-submissions
```

`OTS_REPO_ROOT` remains the trusted core checkout. `OTS_CONTRACT_REPO` supplies links to that core;
`OTS_SUBMISSIONS_REPO` selects the only repository whose proof webhooks are accepted. Leaving the
latter unset keeps intake closed while localhost still links to the intended submissions repository.
Production requires both settings and separate repositories.

Install the Pull requests webhook on the submissions repository. [Deployment](../service/deploy/README.md)
defines the bot token's permissions, the isolation and the launch checks. Only maintainers update
the trusted checkout.

For an existing installation, stop the worker, update the core Git remote, and set both variables
in the public environment file. Restart the web and worker only when the applicable launch checks
pass. Historical rows and outbox entries retain their original PR repository; they are never
silently reassigned to the new repository. The bootstrap script preserves existing environment files.
