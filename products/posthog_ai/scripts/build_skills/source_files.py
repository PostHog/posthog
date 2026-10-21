"""Reading skill source files: the text-file guard and offset-to-line mapping."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_BINARY_CHECK_SIZE = 8192

_ALLOWED_SUBDIRS = {"references", "scripts"}


@dataclass(frozen=True)
class TextPosition:
    line: int
    col: int


def _line_col(text: str, offset: int) -> TextPosition:
    return TextPosition(
        line=text.count("\n", 0, offset) + 1,
        col=offset - text.rfind("\n", 0, offset),
    )


def _bundle_files(skill_dir: Path) -> Iterator[Path]:
    """Every file under the skill's references/ and scripts/ directories.

    Sorted at each level, so the built ZIP is reproducible.
    """
    for subdir_name in sorted(_ALLOWED_SUBDIRS):
        subdir = skill_dir / subdir_name
        if not subdir.is_dir():
            continue
        for root, dirs, filenames in os.walk(subdir):
            dirs[:] = sorted(dirs)
            for filename in sorted(filenames):
                yield Path(root) / filename


def _assert_text_file(file_path: Path) -> None:
    """Raise ValueError if file appears to be binary (contains null bytes)."""
    with open(file_path, "rb") as f:
        chunk = f.read(_BINARY_CHECK_SIZE)
    if b"\x00" in chunk:
        raise ValueError(
            f"Binary file not supported in skill directory: {file_path.name}. Only text-based files are allowed."
        )
