"""Static RISC-V image sizes, pinned to the submission that was measured."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "riscv-program-sizes.json"


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


def for_submission(sub) -> ProgramSize | None:
    if sub.track != "upper-riscv" or sub.status != "verified":
        return None
    detail = sub.detail_dict
    value = detail.get("riscv_program_size", historical_sizes().get(getattr(sub, "id", None)))
    value = validate(value, sub.commit, detail.get("contract"))
    return ProgramSize(value["instructions"], value["data_bytes"]) if value else None
