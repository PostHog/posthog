"""Render compact insight results as plain text for subscription delivery.

Subscriptions deliver an insight as a screenshot, which is the wrong shape for a
SQL-backed table of a few values: the numbers can't be read on a phone, can't be
copied, and disappear entirely when the export fails. For results small enough to
read at a glance we render the values themselves, so the delivery carries the data
and not only a picture of it.

Only tabular results (HogQL / DataVisualizationNode, where a row is a list of cells)
are rendered. Chart-shaped results — trends, funnels, retention — stay images, since
a series of many points is what the screenshot is actually good at.
"""

from __future__ import annotations

import math
from typing import Any

# Rows beyond this are summarized as a count — a long table is exactly the case where the
# screenshot became unreadably tall, and a preview plus "view in PostHog" beats both.
MAX_ROWS = 10
# Wide tables wrap badly in Slack, so past this the image really is the better rendering.
MAX_COLUMNS = 6
MAX_CELL_LENGTH = 100
MAX_TEXT_LENGTH = 2000


def build_results_text_for_snapshot(snapshot: dict[str, Any]) -> str | None:
    """Render the ``query_results`` of one insight delivery snapshot, if it's compact enough."""
    query_results = snapshot.get("query_results")
    if not isinstance(query_results, dict):
        return None
    return build_results_text(query_results.get("result"), query_results.get("columns"))


def build_results_text(results: Any, columns: Any) -> str | None:
    """Plain-text rendering of a tabular result, or None when text isn't the right shape.

    The output carries no backticks, so callers can safely wrap it in a fenced block.
    """
    shown = _preview_rows(results)
    if shown is None:
        return None

    header = _header_labels(columns, width=max(len(row) for row in shown))
    if len(header) > MAX_COLUMNS:
        return None

    text = _render_single_row(header, shown[0]) if len(shown) == 1 else _render_table(header, shown)
    hidden = len(results) - len(shown)
    if hidden:
        text += f"\n... and {hidden:,} more row{'' if hidden == 1 else 's'}"
    return _cap_length(text) or None


def _cap_length(text: str) -> str:
    """Drop whole lines to fit the budget.

    A character-level cut would leave a half-written number reading as a real one, which is
    the one failure this whole rendering can't afford.
    """
    if len(text) <= MAX_TEXT_LENGTH:
        return text
    kept: list[str] = []
    budget = MAX_TEXT_LENGTH - len("\n... (truncated)")
    for line in text.splitlines():
        if budget - len(line) - 1 < 0:
            break
        kept.append(line)
        budget -= len(line) + 1
    return "\n".join([*kept, "... (truncated)"])


def _preview_rows(results: Any) -> list[list[Any]] | None:
    """The rows we'd render, or None if this isn't a tabular result.

    Only the preview is inspected — a result can hold hundreds of thousands of rows and
    the shape check would otherwise walk all of them to decide the same thing.
    """
    if not isinstance(results, list) or not results:
        return None
    preview = results[:MAX_ROWS]
    if not all(isinstance(row, (list, tuple)) and row for row in preview):
        return None
    return [list(row) for row in preview]


def _header_labels(columns: Any, width: int) -> list[str]:
    labels: list[str] = []
    for index in range(width):
        label = None
        if isinstance(columns, (list, tuple)) and index < len(columns):
            label = _cell(columns[index])
        labels.append(label or f"Column {index + 1}")
    return labels


def _render_single_row(header: list[str], row: list[Any]) -> str:
    """One row reads better as `label: value` lines than as a two-line table."""
    label_width = max(len(label) for label in header) + len(":")
    return "\n".join(
        f"{(label + ':').ljust(label_width)} {_cell(value)}" for label, value in zip(header, _padded(row, len(header)))
    )


def _render_table(header: list[str], rows: list[list[Any]]) -> str:
    cells = [[_cell(value) for value in _padded(row, len(header))] for row in rows]
    widths = [max(len(header[i]), *(len(row[i]) for row in cells)) for i in range(len(header))]
    lines = ["  ".join(label.ljust(widths[i]) for i, label in enumerate(header))]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)) for row in cells)
    return "\n".join(line.rstrip() for line in lines)


def _padded(row: list[Any], width: int) -> list[Any]:
    """Ragged rows happen — a short row shouldn't shift values under the wrong header."""
    return list(row[:width]) + [None] * (width - len(row))


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        text = f"{value:,}"
    elif isinstance(value, float):
        if not math.isfinite(value):
            text = "-"
        elif value == int(value):
            text = f"{int(value):,}"
        else:
            text = f"{value:,.2f}"
    else:
        text = str(value)

    # Backticks would break out of the fenced block the caller wraps this in, and a
    # newline inside a cell would break the column alignment.
    text = text.replace("`", "'")
    text = " ".join(text.split())
    if len(text) > MAX_CELL_LENGTH:
        text = text[: MAX_CELL_LENGTH - 1] + "…"
    return text
