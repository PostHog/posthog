"""Transform materialized insight endpoint responses from flat HogQL to rich insight format.

When insight queries (TrendsQuery, RetentionQuery, LifecycleQuery) are materialized,
the S3 table stores flat HogQL data. At read time, SELECT * returns flat rows.
This module transforms those flat rows back into the insight-specific response shape
that users expect (matching what the non-materialized path produces).
"""

import re
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Union, cast

import structlog

from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team import Team

if TYPE_CHECKING:
    from posthog.hogql_queries.insights.lifecycle.lifecycle_query_runner import LifecycleQueryRunner
    from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner
    from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner

    InsightRunner = Union["LifecycleQueryRunner", "RetentionQueryRunner", "TrendsQueryRunner"]

logger = structlog.get_logger(__name__)


class MaterializedSeriesMismatchError(Exception):
    """Raised when a materialized trends table's series count differs from the current query definition.

    This indicates the endpoint query was edited after materialization and the stored table
    is now stale. Callers should trigger a re-materialization.
    """


def transform_materialized_insight_response(
    result: dict,
    original_query: dict,
    team: Team,
    now: datetime | None = None,
) -> None:
    """Transform flat HogQL results in-place into insight-specific response shape.

    Args:
        result: The result.data dict from _execute_query_and_respond(). Modified in-place.
        original_query: The original insight query definition (TrendsQuery, etc.)
        team: The team for query runner context.
        now: Pin date range to this timestamp (e.g., saved_query.last_run_at) instead of datetime.now().
    """
    query_kind = original_query.get("kind")

    if query_kind == "TrendsQuery":
        _transform_trends(result, original_query, team, now)
    elif query_kind == "LifecycleQuery":
        _transform_lifecycle(result, original_query, team, now)
    elif query_kind == "RetentionQuery":
        _transform_retention(result, original_query, team, now)


def _make_runner(original_query: dict, team: Team, now: datetime | None = None) -> "InsightRunner":
    """Instantiate a query runner from the original query for formatting context.

    Callers are responsible for passing a TrendsQuery, LifecycleQuery, or RetentionQuery —
    the return type is narrowed to the corresponding runner union so `query_date_range`,
    `format_results` etc. are statically visible.
    """
    modifiers_dict = original_query.get("modifiers") or {}
    modifiers = HogQLQueryModifiers(**modifiers_dict)
    runner = cast(
        "InsightRunner",
        get_query_runner(
            query=original_query,
            team=team,
            modifiers=modifiers,
        ),
    )
    if now is not None:
        # Pin the date range to materialization time so response labels reflect
        # when the data was snapshotted, not when the request was served.
        runner.query_date_range.pin_now(now)
    return runner


def _strip_hogql_fields(result: dict) -> None:
    """Remove HogQL-specific fields that don't belong in insight responses."""
    for field in ("columns", "types", "limit", "offset", "query"):
        result.pop(field, None)


_TEMPORAL_TYPE_RE = re.compile(r"\b(?:Date|DateTime|DateTime64|Date32)\b")


def _is_temporal_type(type_str: str) -> bool:
    """True for any Date/DateTime variant, including Nullable/Array/LowCardinality wrappings."""
    return bool(_TEMPORAL_TYPE_RE.search(type_str))


def _extract_type_str(entry: Any) -> str | None:
    """Accept both `[[col_name, type_str], ...]` (real API) and `[type_str, ...]` (mocks)."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, list | tuple) and len(entry) >= 2 and isinstance(entry[1], str):
        return entry[1]
    return None


def _coerce_temporal_columns(rows: list, types: list | None) -> None:
    """Parse ISO strings into ``datetime`` objects for every Date/DateTime column.

    HogQL's response pipeline stringifies all Date/DateTime values regardless of name,
    but the insight runners call .strftime() on them. We use the ``types`` metadata to
    find temporal columns so this works for any column name (``date``, ``timestamp``,
    custom aliases), not just ``date``. Rows can be tuples, so we replace the row in
    the outer list.
    """
    if not types:
        return
    temporal_indices = [i for i, entry in enumerate(types) if (t := _extract_type_str(entry)) and _is_temporal_type(t)]
    if not temporal_indices:
        return
    for i, row in enumerate(rows):
        new_row: list | None = None
        for col_idx in temporal_indices:
            if col_idx >= len(row):
                continue
            value = row[col_idx]
            if isinstance(value, list):
                coerced: Any = [datetime.fromisoformat(item) if isinstance(item, str) else item for item in value]
            elif isinstance(value, str):
                coerced = datetime.fromisoformat(value)
            else:
                continue
            if new_row is None:
                new_row = list(row)
            new_row[col_idx] = coerced
        if new_row is not None:
            rows[i] = new_row


def _transform_trends(result: dict, original_query: dict, team: Team, now: datetime | None = None) -> None:
    runner = cast("TrendsQueryRunner", _make_runner(original_query, team, now))

    columns = result.get("columns", [])
    rows = result.get("results", [])

    if not rows:
        result["results"] = []
        _strip_hogql_fields(result)
        return

    _coerce_temporal_columns(rows, result.get("types"))

    series_index_col = columns.index("__series_index") if "__series_index" in columns else None
    groups: dict[int, list] = defaultdict(list)
    for row in rows:
        idx = row[series_index_col] if series_index_col is not None else 0
        groups[idx].append(row)

    expected_series_count = len(runner.series)

    # A row tagged with a series index the current query no longer defines is real drift:
    # the table was built for a superset. Missing indices are NOT drift — filters or sparse
    # UNION ALL branches can legitimately leave a series with zero rows at read time.
    if groups and max(groups.keys()) >= expected_series_count:
        raise MaterializedSeriesMismatchError(
            f"Materialized table has series index {max(groups.keys())} "
            f"but current query defines only {expected_series_count} series. "
            f"The endpoint query was likely edited after materialization."
        )

    # Build one response per expected series (not per non-empty bucket) so filtered-to-empty
    # series keep their positional slot — build_series_response handles empty results cleanly.
    per_series_responses: list[HogQLQueryResponse] = [
        HogQLQueryResponse(results=groups.get(i, []), columns=columns) for i in range(expected_series_count)
    ]

    returned_results: list[list[dict[str, Any]]] = []
    for i, response in enumerate(per_series_responses):
        returned_results.append(runner.build_series_response(response, runner.series[i], expected_series_count))

    final_result, has_more = runner.format_results(returned_results)

    result["results"] = final_result
    result["hasMore"] = has_more
    _strip_hogql_fields(result)


def _transform_lifecycle(result: dict, original_query: dict, team: Team, now: datetime | None = None) -> None:
    runner = cast("LifecycleQueryRunner", _make_runner(original_query, team, now))

    columns = result.get("columns", [])
    rows = result.get("results", [])

    if not rows:
        result["results"] = []
        _strip_hogql_fields(result)
        return

    _coerce_temporal_columns(rows, result.get("types"))

    response = HogQLQueryResponse(results=rows, columns=columns)
    result["results"] = runner.format_results(response)
    _strip_hogql_fields(result)


def _transform_retention(result: dict, original_query: dict, team: Team, now: datetime | None = None) -> None:
    runner = cast("RetentionQueryRunner", _make_runner(original_query, team, now))

    columns = result.get("columns", [])
    rows = result.get("results", [])

    if not rows:
        result["results"] = []
        _strip_hogql_fields(result)
        return

    response = HogQLQueryResponse(results=rows, columns=columns)
    result["results"] = runner.format_results(response)
    _strip_hogql_fields(result)
