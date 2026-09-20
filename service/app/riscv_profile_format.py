"""Data-only format for owner-maintained example executions; standard library only."""
from __future__ import annotations

import json
import re

REGISTRY_PATH = "riscv-profiles.json"
MAX_BYTES = 1024 * 1024
MAX_PROFILES = 1000
MAX_ROWS = 512
MAX_CYCLES = 1_000_000
# The pinned RV64IM subset. ECALL is represented by HASH or HALT, never counted twice.
INSTRUCTIONS = frozenset("""
ADD SUB SLL SRL SRA AND OR XOR SLT SLTU ADDI ANDI ORI XORI SLTI SLTIU SLLI SRLI SRAI
LUI AUIPC LD SD LW LWU SW LB LH LBU LHU SB SH BEQ BNE BLT BGE BLTU BGEU JAL JALR
ADDIW SUBW SRLW SLLIW SRLIW FENCE MUL MULH MULHSU MULHU DIV DIVU REM REMU HASH HALT
""".split())


def _hex(value, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _integer(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def validate_profile(value) -> dict:
    if (not isinstance(value, dict) or set(value) - {"commit", "contract", "accepted", "rows", "notes"}
            or not _hex(value.get("commit"), 40) or not _hex(value.get("contract"), 64)
            or type(value.get("accepted")) is not bool
            or not isinstance(value.get("rows"), list) or not 1 <= len(value["rows"]) <= MAX_ROWS
            or not isinstance(value.get("notes", ""), str) or len(value.get("notes", "")) > 4096):
        raise ValueError("expected commit, contract, accepted, rows and optional notes")
    rows, seen = [], set()
    for row in value["rows"]:
        if not isinstance(row, dict):
            raise ValueError("each row must be an object")
        instruction, count, bits = row.get("instruction"), row.get("count"), row.get("input_bits")
        if (not isinstance(instruction, str) or instruction not in INSTRUCTIONS
                or not _integer(count, 1, MAX_CYCLES)):
            raise ValueError("unknown instruction or invalid count")
        keys = {"instruction", "count", "input_bits"} if instruction == "HASH" else {"instruction", "count"}
        if set(row) != keys or (instruction == "HASH" and not _integer(bits, 0, 512 * MAX_CYCLES)):
            raise ValueError("only HASH rows require input_bits; counts and lengths must be integers")
        identity = (instruction, bits)
        if identity in seen:
            raise ValueError("combine duplicate instruction/input-length rows")
        seen.add(identity)
        price = max(1, (bits + 511) // 512) if instruction == "HASH" else 1
        rows.append({"instruction": instruction, "executions": count, "bits": bits,
                     "price": price, "cycles": count * price,
                     "label": f"HASH · {bits:,} input bits" if instruction == "HASH" else instruction})
    cycles = sum(row["cycles"] for row in rows)
    if cycles > MAX_CYCLES or sum(row["executions"] for row in rows if row["instruction"] == "HALT") != 1:
        raise ValueError("a completed execution needs exactly one HALT and at most one million cycles")
    for row in rows:
        row["share"] = round(100 * row["cycles"] / cycles, 1)
    rows.sort(key=lambda row: -row["cycles"])
    return {"commit": value["commit"], "contract": value["contract"], "accepted": value["accepted"],
            "rows": rows, "cycles": cycles, "executions": sum(row["executions"] for row in rows)}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_registry(raw: bytes) -> tuple[dict, dict]:
    """Return valid profiles and per-entry errors; one bad edit cannot hide other profiles."""
    if len(raw) > MAX_BYTES:
        raise ValueError("profile registry exceeds 1 MiB")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid profile registry JSON") from exc
    if (not isinstance(data, dict) or set(data) != {"version", "profiles"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["profiles"], dict) or len(data["profiles"]) > MAX_PROFILES):
        raise ValueError("expected version 1 and at most 1000 profiles")
    profiles, errors = {}, {}
    for sid, value in data["profiles"].items():
        try:
            if not _hex(sid, 32):
                raise ValueError("profile key must be the 32-character submission ID")
            profiles[sid] = validate_profile(value)
        except ValueError as exc:
            errors[sid] = str(exc)
    return profiles, errors
