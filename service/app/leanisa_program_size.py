"""Static leanISA bytecode slots, bound to the checked source and contract."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def historical_sizes() -> dict:
    return json.loads((Path(__file__).resolve().parents[1] / "leanisa-program-sizes.json").read_text())["measurements"]


@dataclass(frozen=True)
class ProgramSize:
    instructions: int

    @property
    def instruction_label(self) -> str:
        return f"{self.instructions:,}"

    @property
    def instruction_description(self) -> str:
        return "Slots in the fixed bytecode table, including padding and the halt slot."


def validate(value, commit, contract) -> dict | None:
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
            or value.get("commit") != commit or not value.get("contract") or value["contract"] != contract):
        return None
    n = value.get("instructions")
    if type(n) is not int or not 1 <= n <= 262144 or n & (n - 1):
        return None
    return {"version": 1, "commit": commit, "contract": contract, "instructions": n}


def for_submission(sub) -> ProgramSize | None:
    if sub.track != "upper-leanisa" or sub.status != "verified":
        return None
    value = sub.detail_dict.get("leanisa_program_size", historical_sizes().get(getattr(sub, "id", None)))
    value = validate(value, sub.commit, sub.detail_dict.get("contract"))
    return ProgramSize(value["instructions"]) if value else None
