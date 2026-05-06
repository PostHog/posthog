import json
import hashlib
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


def stable_int(seed: int, idx: int, salt: str, *, bits: int = 48) -> int:
    h = hashlib.sha256(f"{salt}:{seed}:{idx}".encode()).hexdigest()
    return int(h[: bits // 4], 16)


def stable_uuid(seed: int, idx: int, salt: str) -> str:
    h = hashlib.sha256(f"{salt}:{seed}:{idx}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@cache
def load_template(filename: str) -> dict[str, Any]:
    """Load the first record from a reference fixture as a wrapper template.

    Wrappers deep-copy this and override only the LLM-mutable + identity fields,
    so any new fields added to the fixture (and accepted by the parser) come
    along for free without wrapper maintenance.
    """
    path = _FIXTURES_DIR / filename
    with path.open() as f:
        records = json.load(f)
    if not isinstance(records, list) or not records:
        raise ValueError(f"Fixture {path} must be a non-empty JSON list of records")
    first = records[0]
    if not isinstance(first, dict):
        raise ValueError(f"Fixture {path} first record must be a dict, got {type(first).__name__}")
    return first
