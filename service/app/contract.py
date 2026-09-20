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


def upper_compressions_track() -> dict | None:
    """Only the explicitly pinned generic certificate opens the public upper track."""
    certificate = track("upper-compressions") if "upper-compressions" in upper_track_slugs() else None
    if certificate and certificate["kind"] == "upper" and certificate["framework"] == "oracle-algorithm":
        return certificate
    return None


def upper_riscv_track() -> dict | None:
    """A checked machine certificate opens the separate implementation track."""
    certificate = track("upper-riscv") if "upper-riscv" in upper_track_slugs() else None
    if certificate and certificate["kind"] == "upper" and certificate["framework"] == "oracle-algorithm":
        return certificate
    return None


def upper_tracks() -> list[dict]:
    return [t for t in (upper_compressions_track(), upper_riscv_track()) if t is not None]


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
RESULT_COMPATIBILITY = {
    "cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc": {
        "a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb": frozenset({
            "lower-generality-1", "upper-compressions", "upper-riscv",
        }),
    },
}


def compatible_result(slug: str, previous_id: str | None) -> bool:
    """An already verified result for an audited, unchanged statement in this exact revision."""
    return slug in RESULT_COMPATIBILITY.get(contract_id(), {}).get(previous_id, ())
