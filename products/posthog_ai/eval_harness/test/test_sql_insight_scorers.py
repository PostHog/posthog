from __future__ import annotations

import pytest

from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log
from products.posthog_ai.evals.product_analytics.sql_insight_scorers import (
    SavedSqlInsight,
    SqlFollowsDateFilter,
    SqlTimeAxisAscending,
)

DEFAULT_RANGE = {"dateRange": {"date_from": "-14d"}}


def _save(
    sql: str, filters: dict | None = DEFAULT_RANGE, dashboards: list[int] | None = None, result: str = '{"id": 1}'
) -> tuple:
    source: dict = {"kind": "HogQLQuery", "query": sql}
    if filters is not None:
        source["filters"] = filters
    payload: dict = {"name": "Uploads", "query": {"kind": "DataVisualizationNode", "source": source}}
    if dashboards is not None:
        payload["dashboards"] = dashboards
    return ("mcp__posthog__insight-create", payload, result)


def _add_to_dashboard(insight_id: int | str) -> tuple:
    return ("mcp__posthog__insight-update", {"id": insight_id, "dashboards": [7]}, '{"id": 1}')


def _output(*calls: tuple) -> dict:
    return {"raw_log": _raw_tool_log(list(calls)), "prompt": "Save a SQL insight"}


@pytest.mark.parametrize(
    "sql,filters,expected_score",
    [
        ("SELECT count() FROM events WHERE {filters}", DEFAULT_RANGE, 1.0),
        (
            "WITH firsts AS (SELECT person_id, min(timestamp) AS t FROM events WHERE {filters} GROUP BY person_id) "
            "SELECT count() FROM firsts",
            DEFAULT_RANGE,
            1.0,
        ),
        (
            "SELECT count() FROM events WHERE timestamp >= {filters.dateRange.from} "
            "AND timestamp < {filters.dateRange.to}",
            DEFAULT_RANGE,
            1.0,
        ),
        ("SELECT count() FROM events WHERE timestamp >= now() - INTERVAL 14 DAY", DEFAULT_RANGE, 0.0),
        ("SELECT count() FROM events WHERE {filters} AND timestamp >= now() - INTERVAL 14 DAY", DEFAULT_RANGE, 0.0),
        ("SELECT count() FROM events WHERE timestamp BETWEEN '2026-01-01' AND '2026-01-15'", DEFAULT_RANGE, 0.0),
        ("SELECT count() FROM events WHERE {filters}", None, 0.0),
        ("SELECT count() FROM events WHERE {filters(created_at AS timestamp)}", DEFAULT_RANGE, 1.0),
        ("SELECT count() FROM events WHERE {filters(null AS timestamp)}", DEFAULT_RANGE, 0.0),
        (
            "SELECT dateTrunc({filters.interval}, timestamp) AS bucket, count() FROM events GROUP BY bucket",
            DEFAULT_RANGE,
            0.0,
        ),
        (
            "SELECT count() FROM events WHERE {filters} AND timestamp >= toDateTime('2026-01-01 00:00:00')",
            DEFAULT_RANGE,
            0.0,
        ),
        ("SELECT count() FROM events WHERE timestamp BETWEEN {filters.dateRange.from} AND now()", DEFAULT_RANGE, 0.0),
    ],
    ids=[
        "filters_placeholder",
        "filters_inside_cte",
        "date_range_placeholders",
        "hard_coded_window",
        "placeholder_plus_hard_coded_window",
        "date_literal_window",
        "no_default_date_range",
        "column_bound_timestamp",
        "column_bound_null_timestamp",
        "interval_placeholder_only",
        "date_literal_inside_conversion",
        "placeholder_and_clock_in_one_window",
    ],
)
def test_sql_follows_date_filter(sql: str, filters: dict | None, expected_score: float) -> None:
    score = SqlFollowsDateFilter()._run_eval_sync(
        _output(_save(sql, filters)), expected={"sql_follows_date_filter": {}}
    )

    assert score.score == expected_score, score.metadata


DAILY_BY_FILE_TYPE = (
    "SELECT toStartOfDay(timestamp) AS day, properties.file_type AS file_type, count() AS uploads "
    "FROM events WHERE {filters} GROUP BY day, file_type "
)
DAY_SERIES_JOIN = (
    "SELECT d.day AS day, coalesce(c.uploads, 0) AS uploads "
    "FROM (SELECT today() - number AS day FROM numbers(30)) AS d "
    "LEFT JOIN (SELECT toDate(timestamp) AS day, count() AS uploads FROM events WHERE {filters} GROUP BY day) AS c "
    "ON d.day = c.day "
)


@pytest.mark.parametrize(
    "sql,expected_score",
    [
        (DAILY_BY_FILE_TYPE + "ORDER BY day", 1.0),
        (DAILY_BY_FILE_TYPE + "ORDER BY day ASC", 1.0),
        (DAILY_BY_FILE_TYPE + "ORDER BY 1", 1.0),
        (DAILY_BY_FILE_TYPE + "ORDER BY file_type, toStartOfDay(timestamp)", 1.0),
        (DAY_SERIES_JOIN + "ORDER BY day", 1.0),
        (
            "SELECT bucket, sum(uploads) AS uploads FROM (SELECT toStartOfWeek(timestamp) AS bucket, count() AS uploads "
            "FROM events WHERE {filters} GROUP BY bucket) GROUP BY bucket ORDER BY bucket",
            1.0,
        ),
        (
            "WITH weeks AS (SELECT toStartOfWeek(now()) - toIntervalWeek(number) AS week FROM numbers(8)) "
            "SELECT weeks.week AS week FROM weeks ORDER BY week",
            1.0,
        ),
        (
            "WITH daily AS (SELECT toStartOfDay(timestamp) AS day, count() AS uploads FROM events WHERE {filters} "
            "GROUP BY day) SELECT day, uploads FROM daily ORDER BY day",
            1.0,
        ),
        ("WITH events AS (SELECT timestamp FROM events) SELECT timestamp FROM events ORDER BY timestamp", 1.0),
        (
            DAILY_BY_FILE_TYPE
            + "ORDER BY day WITH FILL FROM toStartOfDay({filters.dateRange.from}) TO {filters.dateRange.to} "
            + "STEP toIntervalDay(1)",
            1.0,
        ),
        (DAILY_BY_FILE_TYPE + "ORDER BY day DESC", 0.0),
        (DAY_SERIES_JOIN + "ORDER BY day DESC", 0.0),
        (DAILY_BY_FILE_TYPE + "ORDER BY uploads DESC", 0.0),
        (DAILY_BY_FILE_TYPE + "ORDER BY uploads DESC, day ASC", 0.0),
        (DAILY_BY_FILE_TYPE, 0.0),
    ],
    ids=[
        "alias",
        "alias_asc",
        "position",
        "expression_after_breakdown",
        "generated_day_series_join",
        "outer_query_over_subquery",
        "generated_week_series_cte",
        "bucket_projected_through_cte",
        "cte_shadows_events_table",
        "with_fill_bounded_by_placeholders",
        "desc",
        "generated_day_series_join_desc",
        "no_time_key",
        "value_sorted_before_time",
        "no_order_by",
    ],
)
def test_sql_time_axis_ascending(sql: str, expected_score: float) -> None:
    score = SqlTimeAxisAscending()._run_eval_sync(_output(_save(sql)), expected={"sql_time_axis_ascending": {}})

    assert score.score == expected_score, score.metadata


@pytest.mark.parametrize(
    "calls,expected_score",
    [
        ([_save("SELECT 1", dashboards=[7])], 1.0),
        ([_save("SELECT 1"), _add_to_dashboard(1)], 1.0),
        (
            [_save("SELECT 1", result="id: 10975\nshort_id: Ab3xYz9q\nname: Uploads"), _add_to_dashboard("Ab3xYz9q")],
            1.0,
        ),
        ([_save("SELECT 1"), _add_to_dashboard(2)], 0.0),
        ([_save("SELECT 1")], 0.0),
        (
            [
                (
                    "mcp__posthog__insight-create",
                    {
                        "name": "Uploads",
                        "dashboards": [7],
                        "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}},
                    },
                    '{"id": 1}',
                )
            ],
            0.0,
        ),
    ],
    ids=[
        "created_on_dashboard",
        "added_by_update",
        "added_by_update_with_text_output_short_id",
        "other_insight_added_to_dashboard",
        "not_on_dashboard",
        "typed_insight_only",
    ],
)
def test_saved_sql_insight_on_dashboard(calls: list[tuple], expected_score: float) -> None:
    score = SavedSqlInsight()._run_eval_sync(_output(*calls), expected={"saved_sql_insight": {"on_dashboard": True}})

    assert score.score == expected_score, score.metadata
