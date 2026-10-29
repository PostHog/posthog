from __future__ import annotations

import hashlib
from pathlib import Path


def hash_skill_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def verify_skill_files(expected: dict[str, str], roots: list[str]) -> None:
    for root in roots:
        actual = hash_skill_files(Path(root))
        changed = sorted(name for name in expected.keys() | actual.keys() if expected.get(name) != actual.get(name))
        if changed:
            raise RuntimeError(f"Eval skill snapshot mismatch at {root}: {', '.join(changed[:10])}")
