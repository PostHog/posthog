"""Small append-only JSONL cache primitives used by replay provider calls."""

from __future__ import annotations

import os
import json
from pathlib import Path


def read_jsonl_cache(path: Path, key_fields: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, object]]:
    rows: dict[tuple[str, ...], dict[str, object]] = {}
    if not path.exists():
        return rows
    os.chmod(path.parent, 0o700)
    os.chmod(path, 0o600)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    continue
                key = tuple(str(value[field]) for field in key_fields)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            rows[key] = value
    return rows


def append_jsonl(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
