"""Static RISC-V image sizes, pinned to the submission that was measured."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "riscv-program-sizes.json"
IMAGE_LIMIT_CONTRACT = "56289b3f45a5fe68fba953d268860758045f1ef919dd1555d04909ba185c11dc"
IMAGE_LIMIT_PREDECESSORS = frozenset({
    "133f49c9ceaf596c3bf6aaf0941ffe126a1efe23db0785c8af1288b149cb093e",
    "a78ef575231822314169929fa49a707d7788cebf57669c5ef3af9dde947d25cb",
    "cca4d9add2f2a1d3bdc40381258e6992f146e2f3ad9087706913ff281cff22dc",
})


@lru_cache(maxsize=1)
def historical_sizes() -> dict:
    """Frozen measurements for submissions predating automatic collection, stored in Git."""
    return json.loads(CATALOG.read_text())["measurements"]


@dataclass(frozen=True)
class ProgramSize:
    instructions: int
    data_bytes: int

    @property
    def instruction_label(self) -> str:
        return f"{self.instructions:,}"

    @property
    def data_label(self) -> str:
        return f"{self.data_bytes:,} B"

    @property
    def instruction_description(self) -> str:
        return "Number of instructions in the fixed program, including instructions not executed on a given run."

    @property
    def data_description(self) -> str:
        return "Bytes loaded from the fixed data image at startup. Excludes runtime inputs and working memory."


def validate(value, commit, contract) -> dict | None:
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
            or value.get("commit") != commit or not value.get("contract")
            or value["contract"] != contract):
        return None
    count, data = value.get("instructions"), value.get("data_bytes")
    if type(count) is not int or type(data) is not int or not 0 <= count <= 262144 or not 0 <= data <= 1048576:
        return None
    return {"version": 1, "commit": commit, "contract": contract, "instructions": count, "data_bytes": data}


# Both RISC-V tracks fix a `Riscv.Image`, measured by the same trusted collector.
IMAGE_TRACKS = frozenset({"upper-riscv", "upper-riscv-hint"})


def for_submission(sub) -> ProgramSize | None:
    if sub.track not in IMAGE_TRACKS or sub.status != "verified":
        return None
    detail = sub.detail_dict
    value = detail.get("riscv_program_size", historical_sizes().get(getattr(sub, "id", None)))
    value = validate(value, sub.commit, detail.get("contract"))
    return ProgramSize(value["instructions"], value["data_bytes"]) if value else None


def compatible_image_limit(sub) -> bool:
    """Audited pre-rule images meet the new bound; retain their original credit.

    Only the source-pinned, Git-tracked migration catalog authorizes this. Display
    annotations and arbitrary old receipts cannot grandfather an unmeasured image.
    """
    if sub.track != "upper-riscv" or sub.status != "verified" or sub.detail_dict.get("demo"):
        return False
    return compatible_image_source(sub.id, sub.commit, sub.detail_dict.get("contract"))


def image_limit_in_force() -> bool:
    """The per-source image audit stands while the live contract is the one it was made
    against, or one that `RESULT_COMPATIBILITY` audits as carrying `upper-riscv` forward from
    it. A later pure addition to the contract rotates the id and must not silently drop the
    individually checked ports; anything that is not an audited step does drop them."""
    from . import contract
    return (contract.contract_id() == IMAGE_LIMIT_CONTRACT
            or contract.compatible_result("upper-riscv", IMAGE_LIMIT_CONTRACT))


def compatible_image_source(sid, commit, previous) -> bool:
    """Also used to preserve links to previously approved, individually checked proof ports."""
    if not image_limit_in_force() or previous not in IMAGE_LIMIT_PREDECESSORS:
        return False
    value = validate(historical_sizes().get(sid), commit, previous)
    return bool(value and 4 * value["instructions"] + value["data_bytes"] < 1048576)
