# Core and submissions repositories

| Repository | Contents and role |
|---|---|
| [ots.golf-dev](https://github.com/leanEthereum/ots.golf-dev) | Trusted Lean model, challenge stubs, verifier, website and tooling; no track proofs |
| [ots.golf-submissions](https://github.com/leanEthereum/ots.golf-submissions) | Proof PRs; `main` holds only the template and the pinned core submodule |

The local workspace contains both repositories:

```text
sig.golf/
├── ots.golf-dev/
└── ots.golf-submissions/
```

Run core commands from `ots.golf-dev/` and submission checks from `ots.golf-submissions/`.
Start localhost with `bash service/run-local.sh` from the core repository.
The [committed demo fixtures](../service/demo/submissions.json) populate a fresh local database
automatically. They belong to the website in the core repository; checked proof submissions
belong to `ots.golf-submissions`.

The submissions workspace has a `.contract` submodule pinned to a core commit for local proof
checking. Its PRs create or change one admitted root. The hosted verifier reads that root from the PR's exact
head, using its own core checkout for every protected file and verification tool.

Verification results are reported to the PR in the submissions repository as a commit status and
a comment. A verified improvement becomes the record: the first verified head whose claim strictly
improves the track's record when its verification finishes; on a track without a record, the first
verified head. Pull requests are never merged. Before compilation, the hosted verifier retains
the exact root in a source archive linked from the submission page; operators back up these archives.
The GitHub reference `pull/<N>/head` moves on later pushes and is not a historical archive.
Submissions never change the model, website, or trusted checkout. Repository
identity is retained in each PR URL, so moving intake does not send old result comments to an
unrelated PR with the same number.

## Prepare the submissions repository

Commit and check the core changes, then run:

```sh
python3 tools/prepare_submissions_repo.py .build/ots.golf-submissions
```

The destination must be new. The command creates a local Git repository without submission roots,
adds the pinned core submodule, and stages the initial README, agent instructions and submission
PR template. The reference proofs then arrive as ordinary pull requests, one per track. Its `origin` points to `leanEthereum/ots.golf-submissions`.
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
