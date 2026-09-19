# Proof submissions

Follow `.contract/AGENTS.md`: it is the precise specification of the tracks, exports, root rules
and submission workflow. If `.contract` is empty, run `git submodule update --init --recursive`.

| Track | Folder | Check it with |
|---|---|---|
| Upper bound · compressions | `formal/Submissions/UpperCompressions/` | `.contract/verifier/verify.py upper-compressions --source .` |
| Upper bound · RISC-V cycles | `formal/Submissions/UpperRiscv/` | `.contract/verifier/verify.py upper-riscv --source .` |
| Lower bound · Generality 1/3 | `formal/Submissions/LowerGenerality1/` | `.contract/verifier/verify.py lower-generality-1 --source .` |
| Lower bound · Generality 2/3 | `formal/Submissions/LowerGenerality2/` | `.contract/verifier/verify.py lower-generality-2 --source .` |
| Lower bound · Generality 3/3 | `formal/Submissions/LowerGenerality3/` | `.contract/verifier/verify.py lower-generality-3 --source .` |

Run the check from the root of this checkout. Keep proof PR changes inside one admitted root;
do not edit another track, root `records.json` or `.contract`. Every root must satisfy its own
import policy independently, even though `main` contains record proofs for the other tracks.
PRs from an older `main` remain eligible; subsequent base-branch record updates are not their changes.

After a new record's verdict is durable, the bot copies only its checked root and registry entry
to `main` in a separate commit. It never merges or closes the proof PR. Protected source tags and
bot receipt/verdict comments remain the authority for the original checked source and result.
The submission page's Code link opens the exact checked folder at its original GitHub SHA.
