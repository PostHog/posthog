from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Collection, Mapping
from pathlib import Path

_ASSIGNMENT_RE = re.compile(r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$")
_SAFE_VALUE_RE = re.compile(r"[A-Za-z0-9_\-.:/,@+=]*")
_INLINE_COMMENT_RE = re.compile(r"\s+#.*$")


def read(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except FileNotFoundError:
        return ""


def write(path: Path, text: str) -> None:
    path = path.resolve()
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def values(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _ASSIGNMENT_RE.match(line)
        if match:
            found.setdefault(match.group("key"), []).append(_unquote(match.group("value")))
    return found


def is_safe_value(value: str) -> bool:
    return _SAFE_VALUE_RE.fullmatch(value) is not None


def edit(text: str, *, assign: Mapping[str, str], disable: Collection[str], disable_marker: str, header: str) -> str:
    assert not set(assign) & set(disable)
    for value in assign.values():
        assert is_safe_value(value), "values are written unquoted, so they must not need quoting"

    lines = text.splitlines(keepends=True)
    missing = dict(assign)
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        match = _ASSIGNMENT_RE.match(body)
        if match is None:
            continue
        key = match.group("key")
        if key in assign:
            lines[index] = f"{match.group('prefix')}{key}={assign[key]}{ending}"
            missing.pop(key, None)
        elif key in disable:
            lines[index] = f"{disable_marker}{body}{ending}"

    if missing:
        newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        if not any(line.rstrip("\r\n") == header for line in lines):
            if lines and lines[-1].strip():
                lines.append(newline)
            lines.append(f"{header}{newline}")
        lines.extend(f"{key}={value}{newline}" for key, value in missing.items())
    return "".join(lines)


def _unquote(raw: str) -> str:
    value = raw.strip()
    if value[:1] in ('"', "'"):
        closing = value.find(value[0], 1)
        if closing > 0:
            return value[1:closing]
    return _INLINE_COMMENT_RE.sub("", value)
