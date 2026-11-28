"""Quality checks on the prose and suggested prompts a scout sends to `emit_report` / `edit_report`.

A scout writes its report as JSON inside a command string that is JSON too, so some models escape the
text one level too many and the inbox shows a literal `\\n` or `` \\` `` instead of a line break or
inline code. A `repair` check fixes the text before it is stored. A `hint` check leaves the text alone
and tells the scout in the tool response, so it can correct the report in the same run.

A suggested prompt past a stored bound is a repair too: the prompt is left out and the report is
stored without it, because a prompt is optional and the report is not.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from django.db import models

from posthog.dataclasses import frozen

from products.signals.backend.report_prompts import (
    MAX_SUGGESTED_PROMPT_LENGTH,
    MAX_SUGGESTED_PROMPTS,
    normalize_suggested_prompts,
)


class ReportQualityHintSeverity(models.TextChoices):
    REPAIR = "repair", "repair"
    HINT = "hint", "hint"


class ReportQualityHintField(models.TextChoices):
    TITLE = "title", "title"
    SUMMARY = "summary", "summary"
    SUGGESTED_PROMPTS = "suggested_prompts", "suggested_prompts"


_LITERAL_NEWLINE = re.compile(r"\\r\\n|\\n")
_UNESCAPED_BACKTICK = re.compile(r"(?<!\\)`")
_PR_STYLE_TITLE = re.compile(
    r"^\s*(feat|fix|chore|refactor|docs|perf|test|build|ci|style|revert)(\([^)]*\))?!?:\s", re.IGNORECASE
)


@frozen
class QualityHint:
    check_id: str
    severity: ReportQualityHintSeverity
    field: ReportQualityHintField
    message: str


@frozen
class QualityCheckResult:
    title: str | None
    summary: str | None
    hints: tuple[QualityHint, ...]


@frozen
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
            severity=ReportQualityHintSeverity.REPAIR,
            field=ReportQualityHintField.SUMMARY,
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
            severity=ReportQualityHintSeverity.REPAIR,
            field=ReportQualityHintField.SUMMARY,
            message="The summary had only escaped backticks (\\`), so they were changed to plain backticks.",
        ),
        applies=_has_only_escaped_backticks,
        repair=lambda text: text.replace("\\`", "`"),
    ),
    _QualityCheck(
        hint=QualityHint(
            check_id="pr_style_title",
            severity=ReportQualityHintSeverity.HINT,
            field=ReportQualityHintField.TITLE,
            message=(
                "The title reads like a commit message (for example `fix(scope): ...`). An inbox title names "
                "the problem a reader has, not the change. Rewrite it with edit_report."
            ),
        ),
        applies=lambda text: _PR_STYLE_TITLE.match(text) is not None,
    ),
)


def apply_report_quality_checks(*, title: str | None, summary: str | None) -> QualityCheckResult:
    """Run every check on the fields the call sent. Returns the repaired title and summary, and one hint
    for each check that matched. A field the call omitted (None) is not checked."""
    fields: dict[ReportQualityHintField, str | None] = {
        ReportQualityHintField.TITLE: title,
        ReportQualityHintField.SUMMARY: summary,
    }
    hints: list[QualityHint] = []
    for check in _CHECKS:
        text = fields[check.hint.field]
        if text is None or not check.applies(text):
            continue
        if check.repair is not None:
            fields[check.hint.field] = check.repair(text)
        hints.append(check.hint)
    return QualityCheckResult(
        title=fields[ReportQualityHintField.TITLE],
        summary=fields[ReportQualityHintField.SUMMARY],
        hints=tuple(hints),
    )


@frozen
class SuggestedPromptsRepair:
    prompts: list[str] | None
    hints: tuple[QualityHint, ...]


_PROMPT_TOO_LONG = QualityHint(
    check_id="suggested_prompt_too_long",
    severity=ReportQualityHintSeverity.REPAIR,
    field=ReportQualityHintField.SUGGESTED_PROMPTS,
    message=(
        f"A suggested prompt was longer than {MAX_SUGGESTED_PROMPT_LENGTH} characters, so it was left out and "
        "the report was stored without it. A click sends the exact prompt text, so a long prompt is not cut. "
        f"Keep each prompt within {MAX_SUGGESTED_PROMPT_LENGTH} characters."
    ),
)
_PROMPT_DUPLICATE = QualityHint(
    check_id="duplicate_suggested_prompt",
    severity=ReportQualityHintSeverity.REPAIR,
    field=ReportQualityHintField.SUGGESTED_PROMPTS,
    message="A suggested prompt repeated an earlier one, so the repeat was left out.",
)
_TOO_MANY_PROMPTS = QualityHint(
    check_id="too_many_suggested_prompts",
    severity=ReportQualityHintSeverity.REPAIR,
    field=ReportQualityHintField.SUGGESTED_PROMPTS,
    message=(
        f"A report keeps at most {MAX_SUGGESTED_PROMPTS} suggested prompts, so the first {MAX_SUGGESTED_PROMPTS} "
        "were kept and the rest were left out. Put the prompts that matter most first."
    ),
)


def repair_suggested_prompts(prompts: list[str] | None) -> SuggestedPromptsRepair:
    """Leave out each prompt past a stored bound, keep the rest, and return one hint for each bound that
    left a prompt out.

    A prompt over the length bound is left out, not cut, because a click sends its exact text to an
    agent run. When every prompt the call sent is left out, the result is None and not an empty list,
    because an edit reads an empty list as "take the stored prompts down"."""
    if prompts is None:
        return SuggestedPromptsRepair(prompts=None, hints=())
    normalized = normalize_suggested_prompts(prompts)
    within_length = [prompt for prompt in normalized if len(prompt) <= MAX_SUGGESTED_PROMPT_LENGTH]
    unique = list(dict.fromkeys(within_length))
    kept = unique[:MAX_SUGGESTED_PROMPTS]
    hints = tuple(
        hint
        for hint, left_out in (
            (_PROMPT_TOO_LONG, len(within_length) < len(normalized)),
            (_PROMPT_DUPLICATE, len(unique) < len(within_length)),
            (_TOO_MANY_PROMPTS, len(kept) < len(unique)),
        )
        if left_out
    )
    return SuggestedPromptsRepair(prompts=None if hints and not kept else kept, hints=hints)
