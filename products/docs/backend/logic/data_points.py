"""The query behind a data point: what the page accepts, and one check that it runs."""

import re
import json

from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

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


def run_once(team: Team, query: str) -> tuple[str | None, str | None]:
    """``(value, error)``: the first cell of the first row, or why the query did not run."""
    try:
        response = execute_hogql_query(
            query=query, team=team, query_type="doc_data_point", limit_context=LimitContext.QUERY
        )
    except Exception as err:
        return None, str(err).strip().splitlines()[0][:300] if str(err).strip() else "The query did not run."
    rows = response.results or []
    if not rows or not rows[0]:
        return None, "The query came back with no rows."
    if len(rows) > 1 or len(rows[0]) > 1:
        return None, f"The query came back with {len(rows)} rows and {len(rows[0])} columns. It must give one cell."
    return str(rows[0][0]), None


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
    submit = f'call doc-data-point-submit {{"request_id": "{request_id}", "query": "<the SELECT you ran>", "label": "<what the number counts, in a few words>"}}'
    none = f'call doc-data-point-submit {{"request_id": "{request_id}", "status": "none", "note": "<why the data cannot answer>"}}'
    return "\n".join(
        [
            "The page did not receive a data point. Hand it in now through the PostHog MCP `exec` tool, with the SELECT you ran:",
            submit,
            "If the project's data cannot answer:",
            none,
        ]
    )
