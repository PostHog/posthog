"""Portable JSONL, directory, and prior-bundle input loading."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from products.signals.backend.grouping_replay.artifacts import sha256_file
from products.signals.backend.grouping_replay.engine import load_rows

MAX_REPLAY_SIGNALS = 10_000


@dataclass(frozen=True)
class LoadedInput:
    rows: list[dict[str, object]]
    source_name: str
    sha256: str


def _directory_sha256(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_input(path: Path) -> LoadedInput:
    resolved = path.resolve()
    if resolved.is_file():
        loaded_rows = load_rows(resolved)
        _validate_replay_rows(loaded_rows)
        return LoadedInput(rows=loaded_rows, source_name=resolved.name, sha256=sha256_file(resolved))
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    exported_signals = resolved / "signals.jsonl"
    paths = (
        [exported_signals]
        if exported_signals.is_file()
        else sorted(candidate for candidate in resolved.rglob("*.jsonl") if candidate.is_file())
    )
    if not paths:
        raise ValueError(f"{resolved} contains no JSONL files")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for source in paths:
        for row in load_rows(source):
            document_id = str(row["document_id"])
            if document_id in seen:
                raise ValueError(f"duplicate signal ID across directory input: {document_id}")
            seen.add(document_id)
            row["input_position"] = len(rows)
            rows.append(row)
            if len(rows) > MAX_REPLAY_SIGNALS:
                raise ValueError(
                    f"replay input exceeds the safe limit of {MAX_REPLAY_SIGNALS} signals; "
                    "split larger evaluations into bounded time ranges"
                )
    # Match the materialized training corpus and Rust replay tie-break exactly. Input position is
    # retained as provenance, but equal timestamps must not make assignment depend on file layout.
    rows.sort(key=lambda row: (cast(float, row["timestamp"]), str(row["document_id"])))
    _validate_replay_rows(rows)
    return LoadedInput(
        rows=rows,
        source_name=resolved.name,
        sha256=_directory_sha256(resolved, paths),
    )


def _validate_replay_rows(rows: list[dict[str, object]]) -> None:
    if len(rows) > MAX_REPLAY_SIGNALS:
        raise ValueError(
            f"replay input exceeds the safe limit of {MAX_REPLAY_SIGNALS} signals; "
            "split larger evaluations into bounded time ranges"
        )
    for row in rows:
        weight = row.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, int | float) or weight < 0:
            raise ValueError(f"{row.get('document_id', '<unknown>')}: weight must be a nonnegative number")
