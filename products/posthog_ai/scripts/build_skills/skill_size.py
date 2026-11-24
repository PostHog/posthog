"""The recommended size of a skill's entry file, from the Agent Skills specification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# https://agentskills.io/specification: keep SKILL.md under 500 lines and under 5,000 tokens.
RECOMMENDED_ENTRY_LINES = 500
RECOMMENDED_ENTRY_TOKENS = 5_000
# The specification counts tokens, which this code cannot. Four characters per token is the usual estimate for English.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class EntrySize:
    lines: int
    chars: int

    @property
    def tokens(self) -> int:
        return self.chars // CHARS_PER_TOKEN

    @property
    def over_recommendation(self) -> bool:
        return self.lines > RECOMMENDED_ENTRY_LINES or self.tokens > RECOMMENDED_ENTRY_TOKENS


def measure_entry(path: Path) -> EntrySize:
    text = path.read_text()
    return EntrySize(lines=len(text.splitlines()), chars=len(text))


def size_warning(size: EntrySize) -> str | None:
    if not size.over_recommendation:
        return None
    return (
        f"SKILL.md is {size.lines} lines and about {size.tokens:,} tokens. An agent loads all of it at once. "
        f"Keep it under {RECOMMENDED_ENTRY_LINES} lines and {RECOMMENDED_ENTRY_TOKENS:,} tokens, "
        f"and move detail into references/."
    )
