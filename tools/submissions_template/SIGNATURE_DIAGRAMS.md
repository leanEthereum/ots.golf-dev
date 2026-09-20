# Owner-maintained signature diagrams

To attach a drawing to one verified **upper-compressions** or **upper-riscv** submission,
commit an SVG under `signature-diagrams/` and an entry in `signature-diagrams.json` on
this repository's **main**. This is a maintainer operation, separate from proof PRs.
The website refreshes within about 60 seconds; no server command or deployment is needed.

```json
{
  "version": 1,
  "diagrams": {
    "<submission ID from the website URL>": {
      "commit": "<40-character original checked source SHA>",
      "contract": "<64-character contract ID from the bot verdict>",
      "image": "signature-diagrams/my-scheme.svg",
      "alt": "Describe the scheme, its encoding and what the drawing highlights."
    }
  }
}
```

Use the original checked source SHA, not the bot's record-copy commit. Current record
identities are also in `records.json`; older submissions retain their own identities.
A newer record never inherits an older submission's illustration. Only the ID, source
SHA and contract together select the drawing. It does not affect claims or verification.

Any static drawing is supported: a tree, chains, a graph or another layout. The website
does not infer its structure. Include the digest-to-disclosure encoding in the drawing
where useful. Distinguish illustrative patterns from executions actually measured.

Use a self-contained UTF-8 SVG with a `viewBox`. Its width and height must each be at
most 10,000 units. The site displays the drawing in the approved 760px-wide panel,
with horizontal scrolling on small screens. Keep text readable at that size. The
four initial drawings use a light background, blue revealed values and verification
paths, and grey unused branches. Drawings are displayed as images, never page markup.

Supported elements are `svg`, `g`, `defs`, `title`, `desc`, `style`, `path`, `rect`,
`circle`, `ellipse`, `line`, `polyline`, `polygon`, `text`, `tspan`, `textPath`,
`linearGradient`, `radialGradient`, `stop`, `clipPath`, `mask`, `pattern`, `marker`,
`symbol` and `use`. Resource references must be local `#id` references. Scripts,
event handlers, external resources, embedded HTML, DTDs, animations and CSS imports
are not allowed. Convert unsupported objects to ordinary paths when exporting.
Names use letters, digits, `_` or `-`: `signature-diagrams/<name>.svg`, with no subfolders.

Limits: 64 entries, a 256 KiB registry, 1 MiB and 20,000 elements per SVG, and 16 MiB
across distinct images. Alt text is required and limited to 4,096 characters.
Validate before committing from an up-to-date **core** checkout:

```sh
python3 service/check_signature_diagrams.py ../ots.golf-submissions/signature-diagrams.json
```

The checker uses only the Python standard library. It checks format and static SVG
restrictions, not whether the drawing accurately represents the submitted scheme.
Compare against the exact checked source before publishing.

Delete an entry to remove its panel. An empty registry or deletion of the registry
removes all panels. Invalid entries or images are omitted and logged; valid siblings
remain visible. Malformed whole-file JSON hides all diagrams. A temporary GitHub
outage retains the last complete snapshot and retries. The registry and images are
always fetched at the same immutable revision of `main`, so concurrent edits cannot
mix an old registry with a new drawing. A fresh server rebuilds the cache from GitHub.

Keep these files outside `formal/Submissions/`. The record bot preserves them,
including concurrent owner edits. Proof PRs do not supply website drawings.
