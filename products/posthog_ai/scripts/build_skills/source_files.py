"""Reading skill source files: the text-file guard and offset-to-line mapping."""

from __future__ import annotations

from pathlib import Path

_BINARY_CHECK_SIZE = 8192

_ALLOWED_SUBDIRS = {"references", "scripts"}


def _line_col(text: str, offset: int) -> tuple[int, int]:
    return text.count("\n", 0, offset) + 1, offset - text.rfind("\n", 0, offset)


def _assert_text_file(file_path: Path) -> None:
    """Raise ValueError if file appears to be binary (contains null bytes)."""
    with open(file_path, "rb") as f:
        chunk = f.read(_BINARY_CHECK_SIZE)
    if b"\x00" in chunk:
        raise ValueError(
            f"Binary file not supported in skill directory: {file_path.name}. Only text-based files are allowed."
        )
