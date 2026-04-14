"""Transform materialized insight endpoint responses from flat HogQL to rich insight format.

When insight queries (TrendsQuery, RetentionQuery, LifecycleQuery) are materialized,
the S3 table stores flat HogQL data. At read time, SELECT * returns flat rows.
This module transforms those flat rows back into the insight-specific response shape
that users expect (matching what the non-materialized path produces).
"""

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Union, cast

import structlog

from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team import Team

if TYPE_CHECKING:
    from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
    from posthog.hogql_queries.insights.retention_query_runner import RetentionQueryRunner
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


def _transform_trends(result: dict, original_query: dict, team: Team, now: datetime | None = None) -> None:
    runner = cast("TrendsQueryRunner", _make_runner(original_query, team, now))

    columns = result.get("columns", [])
    rows = result.get("results", [])

    if not rows:
        result["results"] = []
        _strip_hogql_fields(result)
        return

    # Group rows by __series_index (trends uses named column access in build_series_response)
    series_index_col = columns.index("__series_index") if "__series_index" in columns else None
    groups: dict[int, list] = defaultdict(list)
    for row in rows:
        idx = row[series_index_col] if series_index_col is not None else 0
        groups[idx].append(row)

    per_series_responses: list[HogQLQueryResponse] = []
    for series_idx in sorted(groups.keys()):
        per_series_responses.append(
            HogQLQueryResponse(
                results=groups[series_idx],
                columns=columns,
            )
        )

    if len(per_series_responses) != len(runner.series):
        raise MaterializedSeriesMismatchError(
            f"Materialized table has {len(per_series_responses)} series "
            f"but current query defines {len(runner.series)}. "
            f"The endpoint query was likely edited after materialization."
        )

    # Call build_series_response per series, then format_results for post-processing
    returned_results: list[list[dict[str, Any]]] = []
    series_count = len(per_series_responses)
    for i, response in enumerate(per_series_responses):
        series_with_extra = runner.series[i]
        returned_results.append(runner.build_series_response(response, series_with_extra, series_count))

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
