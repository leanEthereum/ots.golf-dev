"""The contract as the service sees it: challenges.json, the pin, the trusted commit."""
from __future__ import annotations

import hashlib
import json
import subprocess
from functools import lru_cache

from .config import settings


def load() -> dict:
    return json.loads((settings.repo_root / "challenges.json").read_text(encoding="utf-8"))


def tracks() -> list[dict]:
    return load()["tracks"]


def track(slug: str) -> dict | None:
    return next((t for t in tracks() if t["slug"] == slug), None)


def frameworks() -> list[dict]:
    """The lower frameworks from the least to the most general, as the site lists them."""
    return sorted(load()["frameworks"], key=lambda f: f["title"])


def framework(slug: str) -> dict | None:
    return next((f for f in frameworks() if f["slug"] == slug), None)


def framework_tracks(slug: str) -> dict[str, dict]:
    """Certificates explicitly linked to this class; historical classes stay separate."""
    model = framework(slug)
    if model is None:
        return {}
    return {kind: certificate for kind in ("lower", "upper")
            if f"{kind}_track" in model and (certificate := track(model[f"{kind}_track"])) is not None}


def track_framework_title(t: dict) -> str:
    """Historical certificates retain their class name when a public framework changes."""
    if t.get("historical_framework_title"):
        return t["historical_framework_title"]
    return "Oracle algorithms" if t["kind"] == "upper" else framework(t["framework"])["title"]


def admitted_upper_track(slug: str) -> dict | None:
    """An upper track is public only when the pinned contract lists it and it is generic."""
    certificate = track(slug) if slug in upper_track_slugs() else None
    if certificate and certificate["kind"] == "upper" and certificate["framework"] == "oracle-algorithm":
        return certificate
    return None


def upper_compressions_track() -> dict | None:
    """Only the explicitly pinned generic certificate opens the public upper track."""
    return admitted_upper_track("upper-compressions")


def upper_riscv_track() -> dict | None:
    """A checked machine certificate opens the separate implementation track."""
    return admitted_upper_track("upper-riscv")


def upper_leanisa_track() -> dict | None:
    """The leanISA implementation track, scored in the same cycle unit as RISC-V."""
    return admitted_upper_track("upper-leanisa")


def upper_riscv_hint_track() -> dict | None:
    """The hinted RISC-V implementation track: the same machine on a prover-chosen view."""
    return admitted_upper_track("upper-riscv-hint")


def upper_tracks() -> list[dict]:
    """Every admitted upper track, in the order the pinned contract lists them. Derived from
    the contract so registering a track opens it; a hard-coded list silently refuses new ones."""
    return [t for slug in upper_track_slugs() if (t := admitted_upper_track(slug)) is not None]


def upper_focus(t: dict) -> str:
    """The phrase that distinguishes one upper track from another wherever the site names it."""
    return t.get("focus", "compressions")


def upper_track_slugs() -> list[str]:
    cfg = load()
    if "upper_tracks" in cfg:
        return cfg["upper_tracks"]
    return [f["upper_track"] for f in cfg["frameworks"] if "upper_track" in f]


def cost_unit(t: dict, claim: int | None = None) -> str:
    unit = t.get("cost_unit", "compressions")
    return unit[:-1] if claim == 1 else unit


def contract_id() -> str:
    cfg = load()
    pin = settings.repo_root / cfg["contract"]["pin_file"]
    return hashlib.sha256(pin.read_bytes()).hexdigest() if pin.is_file() else "unpinned"


@lru_cache(maxsize=1)
def trusted_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(settings.repo_root), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def improves(direction: str, claim: int, record: int | None) -> bool:
    if record is None:
        return True
    return claim > record if direction == "+" else claim < record


# This exact retirement revision only deletes the two unused lower-bound statements.
# Model constants, dependencies, surviving declarations and comparator requirements are
# unchanged. Bind compatibility to BOTH complete pins: a later model edit needs a new audit.
# Keep the original receipt/archive identity; never rewrite an old verdict's contract ID.
# Widening only the keygen resource ceiling preserves already proved upper constructions:
# the same algorithm used at most 1024 compressions, hence also at most 2^20. This is
# compatibility of the proved construction, not a claim that old source compiles unchanged.
# Lower bounds quantify over MORE schemes and need an individually verified proof port.
# Adding the leanISA track is a pure addition to the contract: four new protected files
# (`LeanIsaMachine.lean`, `LeanIsa.lean`, its stub and its comparator config), the new track's
# entry and per-track display metadata in `challenges.json`, three new `require`s in
# `formal/lakefile.lean`, and a `lake-manifest.json` regenerated for the new `leanerVM`
# dependency. No model constant,
# surviving declaration or comparator requirement changes, and no pre-existing package
# revision moves — the root `require cslib` / `require PolyFun` added alongside `leanerVM` hold
# both at exactly the revisions the VCVio pin was already built against, so every existing
# proof compiles against the same dependencies as before. Compose with the audited relation
# below rather than restating it: a result carried into `133f49c9…` under the keygen widening
# keeps precisely the slugs that widening allowed. `upper-leanisa` is new and has no prior
# result to carry.
# Capping verification cost (`Admissible.verifyCost : VerifyCostAtMost verifyBudget`, with
# `verifyBudget = 2^20`) STRENGTHENS admissibility, so this one is not a pure addition and is
# audited per track rather than carried wholesale. It closes a hole in `Secure`: `B` is a budget
# for the whole experiment, which ends with a verification, so an unbounded verifier inflated
# every valid `B` until `B / 2^127 > 1` held vacuously.
RESULT_COMPATIBILITY = {
    # Adding the hinted RISC-V track is a pure addition on top of the verification-cost cap
    # below: three new protected files (`RiscvHint.lean`, its stub and its comparator config)
    # and the new track's entry and display metadata in `challenges.json`. `RiscvHint.lean`
    # imports `RiscvMachine.lean` and `OracleAlgorithm.lean` unchanged and defines only new
    # declarations, so no model constant, surviving declaration, comparator requirement or
    # package revision moves, and every proof checked under `bf2e3478…` proves exactly the same
    # statement here. Compose with the audited relations below rather than restating them:
    # each older contract carries forward precisely the slugs `bf2e3478…` carried from it.
    # `upper-riscv-hint` is new and has no prior result to carry.
    "1d21f233c11a9a424917113e31606db38b2f1c31a25767fdfd1b5b7d85947f28": {
        "bf2e347843dc8a1ff1fd87b38832e7e4f19a07837328e1950f9be290fe97a29d": frozenset({
            "lower-generality-1", "upper-compressions", "upper-riscv", "upper-leanisa",
        }),
        "d3684f44469781b7c19d3f540e0b780f17ff5090595377445faeea0fc425279e": frozenset({
            "lower-generality-1", "upper-compressions", "upper-riscv",
        }),
        "56289b3f45a5fe68fba953d268860758045f1ef919dd1555d04909ba185c11dc": frozenset({
            "lower-generality-1", "upper-compressions", "upper-riscv",
        }),
        "133f49c9ceaf596c3bf6aaf0941ffe126a1efe23db0785c8af1288b149cb093e": frozenset({
            "lower-generality-1", "upper-compressions",
        }),
        "a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb": frozenset({"upper-compressions"}),
        "cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc": frozenset({"upper-compressions"}),
    },
    # The verification-cost cap. Not a pure addition: `Admissible` gained a field, so an old
    # certificate carries forward only where what was already checked implies it.
    #   upper-compressions — its certificate exports `scheme.VerifyCostAtMost <claim>` and the
    #     verifier rejects claim > limits.max_claim = 1_000_000 < 2^20 = verifyBudget. So every
    #     accepted compressions result already proved a strictly tighter bound than the new
    #     field asks for, and `VerifyCostAtMost.mono` supplies it.
    #   upper-riscv — `Implements` equates `scheme.verify` with the machine run as oracle
    #     computations, so they make the same queries, and the machine charges exactly
    #     `blockCost input.1` cycles per hash (`RiscvMachine.execute`) plus one per other
    #     instruction. `Submission.no_fault` rules out faulting paths, so `CyclesAtMost <claim>`
    #     bounds the verifier's compression cost by claim <= 1_000_000 < 2^20 on every path.
    #   lower-generality-1 — quantifies over `Dag.Scheme`, not `OracleAlgorithm.Admissible`.
    #     `Dag.lean` is byte-identical and no model constant moved, so the statement is
    #     unchanged and every verified lower certificate still proves exactly it.
    #   upper-leanisa — deliberately NOT carried. Its clauses (`Faithful`, `Sound`) tie bytecode
    #     to specification by acceptance decisions only and never by query cost, so it is the one
    #     track where an old certificate could rest on the very hole this revision closes. A
    #     leanISA result must be re-checked under this contract. No result exists yet.
    "bf2e347843dc8a1ff1fd87b38832e7e4f19a07837328e1950f9be290fe97a29d": {
        "d3684f44469781b7c19d3f540e0b780f17ff5090595377445faeea0fc425279e": frozenset({
            "lower-generality-1", "upper-compressions", "upper-riscv",
        }),
        "56289b3f45a5fe68fba953d268860758045f1ef919dd1555d04909ba185c11dc": frozenset({
            "lower-generality-1", "upper-compressions", "upper-riscv",
        }),
        "133f49c9ceaf596c3bf6aaf0941ffe126a1efe23db0785c8af1288b149cb093e": frozenset({
            "lower-generality-1", "upper-compressions",
        }),
        "a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb": frozenset({"upper-compressions"}),
        "cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc": frozenset({"upper-compressions"}),
    },
    # Adding the leanISA track is a pure addition on top of the image-budget revision above:
    # four new protected files (`LeanIsaMachine.lean`, `LeanIsa.lean`, its stub and its
    # comparator config), the new track's entry and per-track display metadata in
    # `challenges.json`, three new `require`s in `formal/lakefile.lean`, and a
    # `lake-manifest.json` regenerated for the new `leanerVM` dependency. No model constant,
    # surviving declaration or comparator requirement changes, and no pre-existing package
    # revision moves — the root `require cslib` / `require PolyFun` added alongside `leanerVM`
    # hold both at exactly the revisions the VCVio pin was already built against, so every
    # existing proof compiles against the same dependencies as before. Compose with the
    # relations below rather than restating them: RISC-V carries forward from the image-budget
    # contract but no further, exactly as that audit decided. `upper-leanisa` is new and has no
    # prior result to carry.
    "d3684f44469781b7c19d3f540e0b780f17ff5090595377445faeea0fc425279e": {
        "56289b3f45a5fe68fba953d268860758045f1ef919dd1555d04909ba185c11dc": frozenset({
            "lower-generality-1", "upper-compressions", "upper-riscv",
        }),
        "133f49c9ceaf596c3bf6aaf0941ffe126a1efe23db0785c8af1288b149cb093e": frozenset({
            "lower-generality-1", "upper-compressions",
        }),
        "a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb": frozenset({"upper-compressions"}),
        "cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc": frozenset({"upper-compressions"}),
    },
    # Only the RISC-V image budget changes. RISC-V history is checked per source
    # in riscv_program_size.compatible_image_limit, never grandfathered wholesale.
    "56289b3f45a5fe68fba953d268860758045f1ef919dd1555d04909ba185c11dc": {
        "133f49c9ceaf596c3bf6aaf0941ffe126a1efe23db0785c8af1288b149cb093e": frozenset({
            "lower-generality-1", "upper-compressions",
        }),
        "a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb": frozenset({"upper-compressions"}),
        "cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc": frozenset({"upper-compressions"}),
    },
    "133f49c9ceaf596c3bf6aaf0941ffe126a1efe23db0785c8af1288b149cb093e": {
        previous: frozenset({"upper-compressions", "upper-riscv"}) for previous in (
            "a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb",
            "cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc",
        )
    },
    "cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc": {
        "a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb": frozenset({
            "lower-generality-1", "upper-compressions", "upper-riscv",
        }),
    },
}


def compatible_result(slug: str, previous_id: str | None) -> bool:
    """An audited implication between these exact contracts for an already verified result."""
    return slug in RESULT_COMPATIBILITY.get(contract_id(), {}).get(previous_id, ())
