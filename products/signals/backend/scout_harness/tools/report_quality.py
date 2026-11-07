"""Quality checks on the prose a scout sends to `emit_report` / `edit_report`.

A scout writes its report as JSON inside a command string that is JSON too, so some models escape the
text one level too many and the inbox shows a literal `\\n` or `` \\` `` instead of a line break or
inline code. A `repair` check fixes the text before it is stored. A `hint` check leaves the text alone
and tells the scout in the tool response, so it can correct the report in the same run.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

QualitySeverity = Literal["repair", "hint"]
QualityField = Literal["title", "summary"]

_LITERAL_NEWLINE = re.compile(r"\\r\\n|\\n")
_UNESCAPED_BACKTICK = re.compile(r"(?<!\\)`")
_PR_STYLE_TITLE = re.compile(
    r"^\s*(feat|fix|chore|refactor|docs|perf|test|build|ci|style|revert)(\([^)]*\))?!?:\s", re.IGNORECASE
)


@dataclass(frozen=True)
class QualityHint:
    check_id: str
    severity: QualitySeverity
    field: QualityField
    message: str


@dataclass(frozen=True)
class _QualityCheck:
    hint: QualityHint
    applies: Callable[[str], bool]
    repair: Callable[[str], str] | None = None


def _has_only_literal_newlines(text: str) -> bool:
    # A real line break means the escaping was right and a literal `\n` is likely meant (a code sample).
    return "\n" not in text and _LITERAL_NEWLINE.search(text) is not None


def _has_only_escaped_backticks(text: str) -> bool:
    return "\\`" in text and _UNESCAPED_BACKTICK.search(text) is None


_CHECKS: tuple[_QualityCheck, ...] = (
    _QualityCheck(
        hint=QualityHint(
            check_id="literal_newline_escapes",
            severity="repair",
            field="summary",
            message=(
                "The summary had literal \\n sequences and no line breaks, so they were changed to line breaks. "
                "Send real newlines in the JSON string, escaped one time only."
            ),
        ),
        applies=_has_only_literal_newlines,
        repair=lambda text: _LITERAL_NEWLINE.sub("\n", text),
    ),
    _QualityCheck(
        hint=QualityHint(
            check_id="escaped_backticks",
            severity="repair",
            field="summary",
            message="The summary had only escaped backticks (\\`), so they were changed to plain backticks.",
        ),
        applies=_has_only_escaped_backticks,
        repair=lambda text: text.replace("\\`", "`"),
    ),
    _QualityCheck(
        hint=QualityHint(
            check_id="pr_style_title",
            severity="hint",
            field="title",
            message=(
                "The title reads like a commit message (for example `fix(scope): ...`). An inbox title names "
                "the problem a reader has, not the change. Rewrite it with edit_report."
            ),
        ),
        applies=lambda text: _PR_STYLE_TITLE.match(text) is not None,
    ),
)


def apply_report_quality_checks(
    *, title: str | None, summary: str | None
) -> tuple[str | None, str | None, tuple[QualityHint, ...]]:
    """Run every check on the fields the call sent. Returns the repaired title and summary, and one hint
    for each check that matched. A field the call omitted (None) is not checked."""
    fields: dict[QualityField, str | None] = {"title": title, "summary": summary}
    hints: list[QualityHint] = []
    for check in _CHECKS:
        text = fields[check.hint.field]
        if text is None or not check.applies(text):
            continue
        if check.repair is not None:
            fields[check.hint.field] = check.repair(text)
        hints.append(check.hint)
    return fields["title"], fields["summary"], tuple(hints)
