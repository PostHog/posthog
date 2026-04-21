"""Render the PR-writing Task prompt from an autoresearch result.

The template lives at ``templates/code_handoff.md`` so the prose is easy to
review as markdown. Keeping the renderer here means the activity that
creates the handoff Task stays a thin wrapper.
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE_PATH = Path(__file__).with_name("templates") / "code_handoff.md"

# Keep empty sections readable rather than collapsing them to nothing.
_EMPTY_SECTION_PLACEHOLDER = "_(none)_"


def _format_named_markdown(entries: list[tuple[str, str]]) -> str:
    """Render lane/hypothesis lists as nested sections."""
    if not entries:
        return _EMPTY_SECTION_PLACEHOLDER
    chunks = []
    for filename, contents in entries:
        chunks.append(f"#### `{filename}`\n\n{contents.rstrip()}\n")
    return "\n".join(chunks)


def _prettify_json(raw: str) -> str:
    if not raw:
        return _EMPTY_SECTION_PLACEHOLDER
    try:
        return json.dumps(json.loads(raw), indent=2)
    except json.JSONDecodeError:
        return raw.rstrip()


def render_code_handoff_prompt(
    *,
    query_id: str,
    team_id: int,
    original_sql: str,
    best_sql: str,
    baseline_metrics_json: str,
    best_metrics_json: str,
    last_run_json: str,
    operator_hunches: str,
    suggestions: str,
    lanes: list[tuple[str, str]],
    hypotheses: list[tuple[str, str]],
    reviews: list[tuple[str, str]],
) -> str:
    template = TEMPLATE_PATH.read_text()
    return template.format(
        query_id=query_id,
        team_id=team_id,
        original_sql=original_sql.rstrip() or _EMPTY_SECTION_PLACEHOLDER,
        best_sql=best_sql.rstrip() or _EMPTY_SECTION_PLACEHOLDER,
        baseline_metrics_json=_prettify_json(baseline_metrics_json),
        best_metrics_json=_prettify_json(best_metrics_json),
        last_run_json=_prettify_json(last_run_json),
        operator_hunches=operator_hunches.rstrip() or _EMPTY_SECTION_PLACEHOLDER,
        suggestions=suggestions.rstrip() or _EMPTY_SECTION_PLACEHOLDER,
        lanes_section=_format_named_markdown(lanes),
        hypotheses_section=_format_named_markdown(hypotheses),
        reviews_section=_format_named_markdown(reviews),
    )
