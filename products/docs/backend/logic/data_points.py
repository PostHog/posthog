"""The query behind a data point: what the page accepts, and one check that it runs."""

import re
import json
from datetime import date, datetime
from typing import Any

from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team

from ..facade.enums import DataShape

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")

_READ_START = re.compile(r"^\s*(with|select)\b", re.IGNORECASE)
_HOGQL_TAG = re.compile(r"<hogql\b([^>]*)>(.*?)</hogql>", re.IGNORECASE | re.DOTALL)
_TAG_LABEL = re.compile(r'(?:label|title)="([^"]*)"', re.IGNORECASE)
_TRAILING_SEMICOLON = re.compile(r";\s*$")


def clean_query(query: str) -> str:
    return _TRAILING_SEMICOLON.sub("", query.strip())


def is_read_query(query: str) -> bool:
    """One SELECT (or WITH … SELECT) and nothing after it. The page runs this on every read."""
    cleaned = clean_query(query)
    return bool(_READ_START.match(cleaned)) and ";" not in cleaned


def extract_query(text: str) -> tuple[str, str] | None:
    """The last ``<hogql label="…">SELECT …</hogql>`` in prose, for a run that never called the tool."""
    matches = _HOGQL_TAG.findall(text or "")
    if not matches:
        return None
    attributes, query = matches[-1]
    query = clean_query(query)
    if not is_read_query(query):
        return None
    label = _TAG_LABEL.search(attributes)
    return query, (label.group(1) if label else "").strip()


@frozen
class DataPointRun:
    """What one run of the query gave: its shape, the cell the page shows, or why it did not run."""

    shape: DataShape | None
    value: str | None
    rows: int
    columns: int
    error: str | None


def _is_number(cell: Any) -> bool:
    return isinstance(cell, int | float) and not isinstance(cell, bool)


def _is_moment(cell: Any) -> bool:
    return isinstance(cell, datetime | date) or (isinstance(cell, str) and bool(_ISO_DATE.match(cell)))


def classify(rows: list[list[Any]]) -> DataPointRun:
    """One cell is a number. Two columns of moments and numbers are a series. Anything else is a table."""
    if not rows or not rows[0]:
        return DataPointRun(shape=None, value=None, rows=0, columns=0, error="The query came back with no rows.")
    columns = len(rows[0])
    if len(rows) == 1 and columns == 1:
        return DataPointRun(shape=DataShape.NUMBER, value=str(rows[0][0]), rows=1, columns=1, error=None)
    if columns == 2 and len(rows) >= 2:
        moments = [row[0] for row in rows]
        numbers = [row[1] for row in rows]
        if all(_is_number(cell) for cell in moments) and all(_is_moment(cell) for cell in numbers):
            moments, numbers = numbers, moments
        if all(_is_moment(cell) for cell in moments) and all(_is_number(cell) for cell in numbers):
            return DataPointRun(shape=DataShape.SERIES, value=str(numbers[-1]), rows=len(rows), columns=2, error=None)
    return DataPointRun(shape=DataShape.TABLE, value=None, rows=len(rows), columns=columns, error=None)


def run_once(team: Team, query: str) -> DataPointRun:
    """Runs the query one time and says what shape it has, or why it did not run."""
    try:
        with tags_context(product=Product.POSTHOG_CODE, feature=Feature.DOCS):
            response = execute_hogql_query(
                query=query, team=team, query_type="doc_data_point", limit_context=LimitContext.QUERY
            )
    except Exception as err:
        message = str(err).strip()
        return DataPointRun(
            shape=None,
            value=None,
            rows=0,
            columns=0,
            error=message.splitlines()[0][:300] if message else "The query did not run.",
        )
    return classify([list(row) for row in (response.results or [])])


def extract_structured(text: str) -> dict[str, str] | None:
    """A turn that ended as the JSON the task's schema asked for: ``{status, query, label, note}``."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if not body.startswith("{"):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("status") not in ("ok", "none"):
        return None
    return {key: str(data.get(key) or "") for key in ("status", "query", "label", "note")}


def reminder_text(request_id: str) -> str:
    """The one fixed follow-up a run gets when it wrote prose and no data point."""
    submit = f'call doc-data-point-submit {{"request_id": "{request_id}", "query": "<the SELECT you ran>", "label": "<what it shows, in a few words>"}}'
    none = f'call doc-data-point-submit {{"request_id": "{request_id}", "status": "none", "note": "<why the data cannot answer>"}}'
    return "\n".join(
        [
            "The page did not receive a data point. Hand it in now through the PostHog MCP `exec` tool, with the SELECT you ran:",
            submit,
            "If the project's data cannot answer:",
            none,
        ]
    )
