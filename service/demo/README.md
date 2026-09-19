# Demo leaderboard fixtures

`submissions.json` holds the fictional submissions (by Satoshi Nakamoto, Vitalik Buterin and Hal
Finney) that populate the local leaderboard. They are website fixtures, not proofs: fictional
attribution establishes no theorem, and record decisions for real submissions ignore demo rows.

## Usage

```sh
cd service
uv sync --frozen
OTS_PHONY=1 ./run-local.sh
```

With this explicit opt-in, startup creates the local database and loads the fixtures. The default
`OTS_PHONY=0` skips seeding and hides existing demo rows without deleting their IDs or dates.
`seed_demo.py --refresh` reconciles the fixtures by hand (development mode and a loopback site URL
only). Production and the normal live-maintenance workflow do not use these fixtures.

## Entry format

| Field | Meaning |
|---|---|
| `id` | permanent fixture ID; keep it stable when editing a row |
| `track` | track slug |
| `login` | fictional solver |
| `hours_ago` | age at first insertion |
| `claim` | absolute claim, in the track's unit |
| `is_record` | whether the row is a record |
| `assisted_by`, `co_authors`, `notes` | optional attribution and notes |

Refreshing resets existing demo rows to their fixture claims and inserts missing entries,
preserving database IDs and dates. Every entry carries the visible demo label.

## Keeping fixtures current

On each track, the rows form a record history whose best record equals the claim of that track's
reference proof; older records and non-record attempts may be worse. When a reference proof
changes, update that track's best claim here. RISC-V rows are seeded only while that track is
admitted in the core metadata.
