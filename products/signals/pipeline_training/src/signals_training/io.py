from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

JsonObject = dict[str, object]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def read_jsonl(path: Path) -> Iterator[tuple[int, JsonObject]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            yield line_number, cast(JsonObject, value)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def write_jsonl(path: Path, rows: Iterable[JsonObject]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(canonical_json(row))
                handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_paths(paths: Iterable[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    seen: set[Path] = set()
    position = 0
    for value in paths:
        path = value.resolve()
        if path in seen:
            continue
        seen.add(path)
        prefix = f"{position:03d}:{path.name}"
        position += 1
        if path.is_file():
            result[prefix] = sha256_file(path)
        elif path.is_dir():
            for child in sorted(
                (
                    value
                    for value in path.rglob("*")
                    if value.is_file() and value.name not in {"_stage.json", "stage.log"}
                ),
                key=lambda value: value.relative_to(path).as_posix(),
            ):
                result[f"{prefix}/{child.relative_to(path)}"] = sha256_file(child)
        else:
            result[prefix] = "missing"
    return result


def parse_epoch(value: object, location: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{location}: timestamp must not be boolean")
    if isinstance(value, (int, float)):
        epoch = float(value)
    elif isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise ValueError(f"{location}: invalid timestamp {value!r}") from error
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        epoch = parsed.timestamp()
    else:
        raise ValueError(f"{location}: timestamp must be a string or number")
    if not math.isfinite(epoch):
        raise ValueError(f"{location}: timestamp must be finite")
    return epoch


def require_string(row: JsonObject, field: str, location: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{location}: {field} must be a non-empty string")
    return value


def require_string_list(row: JsonObject, field: str, location: str, *, non_empty: bool = False) -> list[str]:
    value = row.get(field)
    if not isinstance(value, list) or (non_empty and not value):
        qualifier = "a non-empty" if non_empty else "an"
        raise ValueError(f"{location}: {field} must be {qualifier} array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{location}: {field}[{index}] must be a non-empty string")
        result.append(item)
    if len(result) != len(set(result)):
        raise ValueError(f"{location}: {field} contains duplicate values")
    return result


def require_vector(row: JsonObject, field: str, location: str, width: int = 1536) -> None:
    value = row.get(field)
    if not isinstance(value, list) or len(value) != width:
        raise ValueError(f"{location}: {field} must contain exactly {width} numbers")
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ValueError(f"{location}: {field}[{index}] must be finite")


def require_nonzero_vector(row: JsonObject, field: str, location: str, width: int = 1536) -> None:
    require_vector(row, field, location, width)
    values = cast(list[float], row[field])
    if not any(abs(float(value)) > 1e-12 for value in values):
        raise ValueError(f"{location}: {field} must not be a zero vector")
