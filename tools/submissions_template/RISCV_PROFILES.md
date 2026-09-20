# Owner-maintained RISC-V profiles

Edit [`riscv-profiles.json`](riscv-profiles.json) on this repository's **main** to add,
update or remove a table on a particular RISC-V submission page. This is a maintainer
operation, separate from proof PRs. The website checks this file every 60 seconds;
no server command or redeployment is needed. Reload the submission page after it refreshes.

Each key under `profiles` is the submission ID from its `ots.golf/submissions/<id>` URL.
The entry's `commit` is the **original checked source SHA**, not the bot's record-copy
commit. Its `contract` is the 64-character contract ID from that submission's bot verdict.
For a current record, all three values are also in `records.json`.

The file has this shape (replace the placeholders with real identities and measurements):

```json
{
  "version": 1,
  "profiles": {
    "<32-character submission ID>": {
      "commit": "<40-character checked source SHA>",
      "contract": "<64-character contract ID>",
      "accepted": true,
      "notes": "How this particular input was generated and measured.",
      "rows": [
        {"instruction": "ADDI", "count": 10},
        {"instruction": "HASH", "input_bits": 192, "count": 4},
        {"instruction": "HASH", "input_bits": 6080, "count": 1},
        {"instruction": "HALT", "count": 1}
      ]
    }
  }
}
```

Record one complete measured execution. `accepted` records its result; `notes` is optional
and retained in GitHub, not displayed on the website. Use uppercase instruction names from the
competition's pinned RV64IM subset. `HASH` and `HALT` replace the corresponding ECALL executions;
do not also add an `ECALL` row. A complete execution has exactly one HALT.

`count` is a positive integer. For HASH, `input_bits` is the nonnegative input length;
combine calls with the same length into one row. Other instructions have no `input_bits`.
Combine repeated ordinary instructions too. Omit unexecuted instructions.

The website derives prices and totals: one cycle for ordinary instructions and HALT;
`max(1, ceil(input_bits / 512))` for HASH. The approved table shows **Instruction**, **Count**,
and **Share of run** (the percentage of measured cycles). HASH prices appear beside their
input lengths. Rows are sorted by cycle contribution. No summary cards or explanatory prose
are added to the submission page.

From an up-to-date core checkout, validate before committing:

```sh
python3 service/check_riscv_profiles.py ../ots.golf-submissions/riscv-profiles.json
```

The checker needs only Python's standard library. It validates structure and arithmetic, not
that the submitted program actually produced these counts. Measure the exact checked verifier
yourself before publishing a profile. The file is limited to 1 MiB, 1,000 profiles and 512 rows per
profile; execution cost must be at most 1,000,000 cycles and at most that submission's certified
claim. HASH rows are not an instruction-set extension.

Only a verified RISC-V submission with matching ID, commit and contract gets the table.
Profiles do not change claims, statuses, records, proof roots or verification. A later record
does not inherit an earlier submission's table. Invalid entries are omitted and logged; valid
siblings remain visible. Malformed whole-file JSON hides all tables until fixed. During a
temporary GitHub outage, the website retains its last fetched data.

Delete an entry to remove its table. Deleting the file or replacing `profiles` with `{}` removes
all tables on the next successful refresh. A fresh server reloads the file from GitHub; there is
no durable server-side profile state. The record bot preserves this file, including concurrent
maintainer edits. Keep it outside `formal/Submissions/`, and do not include it in proof PRs.
