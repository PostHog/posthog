"""HogQL for the activity summary assets. Both read the dogfood project's events (`LABELS_TEAM_ID`).

`$group_2` is the project group, keyed by the team's uuid.

The inputs queries return free text for the internal cohort only. The projection queries cover every
(project, person) pair and return counts and lengths, so no free text leaves ClickHouse for them.
"""

import datetime
from collections.abc import Collection
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models import Team

from products.signals.dags.inbox_ranking.activity_summary.render import (
    MAX_MCP_SESSIONS_PER_PERSON,
    MAX_UNITS_PER_DAY,
    MCP_LINE_PREFIX_CHARS,
    MCP_STEP_CHARS,
    MIN_WORK_CALLS,
    PLUMBING_TOOL_NAMES,
    UPKEEP_TOOL_PREFIXES,
)
from products.signals.dags.inbox_ranking.dataset.queries import etl_workload, utc_bound

# Each kept MCP source, with the scope presets that mark a person's own calls ("" is no preset).
# Scouts, research and implementation runs carry other presets and are not a person's intent. Slack
# and PostHog AI calls run inside tasks, and the inputs read those tasks' own summaries instead.
MCP_SOURCE_SCOPE_PRESETS: dict[str, tuple[str, ...]] = {
    "mcp": ("user", ""),
}

# The wrapper row of the single `exec` tool. The real tool call it runs is captured as its own row.
MCP_WRAPPER_TOOL_NAME = "exec"

_MCP_FILTERS = f"""
    event = '$mcp_tool_call'
    AND timestamp >= toDateTime({{window_start}}) AND timestamp < toDateTime({{window_end}})
    AND concat(ifNull(toString(properties.source), ''), ':', ifNull(toString(properties.$mcp_scope_preset), '')) IN {{kept_scopes}}
    AND ifNull(toString(properties.$mcp_tool_name), '') != '{MCP_WRAPPER_TOOL_NAME}'
    AND nullIf(toString(properties.$mcp_intent), '') IS NOT NULL
    AND nullIf($group_2, '') IS NOT NULL
"""

_SESSION_KEY = """
    coalesce(
        nullIf(toString(properties.$mcp_conversation_id), ''),
        nullIf(toString(properties.$mcp_session_id), ''),
        nullIf(toString(properties.$session_id), ''),
        concat(distinct_id, '-', toString(toDate(toTimeZone(timestamp, 'UTC'))))
    )
"""

# One row per session with its calls as parallel arrays. groupArray walks the rows in one order for
# every array, so index i of each array is the same call. render.py sorts and filters them. Only the
# newest sessions of each person come back, so a very active person cannot make the read unbounded.
INPUT_MCP_SESSIONS_SQL = f"""
SELECT
    distinct_id,
    $group_2 AS project,
    {_SESSION_KEY} AS session_key,
    groupArray(toTimeZone(timestamp, 'UTC')) AS timestamps,
    groupArray(ifNull(toString(properties.$mcp_tool_name), '')) AS tools,
    groupArray(toString(properties.$mcp_intent)) AS intents
FROM events
WHERE {_MCP_FILTERS}
  AND distinct_id IN {{distinct_ids}}
  AND $group_2 IN {{projects}}
GROUP BY distinct_id, project, session_key
ORDER BY max(timestamp) DESC
LIMIT {MAX_MCP_SESSIONS_PER_PERSON} BY distinct_id
"""

_IS_WORK_CALL = """
    (ifNull(toString(properties.$mcp_tool_name), '') NOT IN {plumbing_tools}
     AND NOT arrayExists(prefix -> startsWith(ifNull(toString(properties.$mcp_tool_name), ''), prefix), {upkeep_prefixes}))
"""

# The projection approximates render.py in SQL, and these filters do not run here:
# - the repeated-job filter and the dedupe of identical lines, so units are overcounted for people
#   with scheduled jobs;
# - secret stripping, whitespace folding and the cut at a word boundary, which change lengths very little.
# A line is estimated from the first and last work intents of the session, each capped like the render.
# Sessions per pair are capped at `MAX_UNITS_PER_DAY` per active day, like the burst cap.
# The pair is (project, distinct_id), not (project, person): a person with several distinct ids is
# counted more than once. The calibration ratio against the inputs asset absorbs the length error.
PROJECTION_MCP_SQL = f"""
SELECT
    distinct_id,
    project,
    least(
        countIf(work_calls >= {MIN_WORK_CALLS}),
        {MAX_UNITS_PER_DAY} * uniqExactIf(day, work_calls >= {MIN_WORK_CALLS})
    ) AS mcp_sessions,
    avgIf(line_chars, work_calls >= {MIN_WORK_CALLS}) AS mcp_avg_line_chars
FROM (
    SELECT
        distinct_id,
        $group_2 AS project,
        {_SESSION_KEY} AS session_key,
        toDate(toTimeZone(max(timestamp), 'UTC')) AS day,
        countIf({_IS_WORK_CALL}) AS work_calls,
        least(length(argMinIf(toString(properties.$mcp_intent), timestamp, {_IS_WORK_CALL})), {MCP_STEP_CHARS})
            + least(length(argMaxIf(toString(properties.$mcp_intent), timestamp, {_IS_WORK_CALL})), {MCP_STEP_CHARS})
            + {MCP_LINE_PREFIX_CHARS} AS line_chars
    FROM events
    WHERE {_MCP_FILTERS}
    GROUP BY distinct_id, project, session_key
)
GROUP BY distinct_id, project
HAVING mcp_sessions > 0
"""

# The projection aggregates every pair over 28 days of MCP calls, so it gets the spill guard of the
# other wide reads in this dag on top of the time limit.
_PROJECTION_SETTINGS = HogQLGlobalSettings(
    max_execution_time=600,
    max_memory_usage=20 * 1024**3,
    max_bytes_before_external_group_by=10 * 1024**3,
)
_INPUT_SETTINGS = HogQLGlobalSettings(max_execution_time=600)


def _strings(values: Collection[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=value) for value in sorted(values)])


def kept_scopes() -> list[str]:
    return [f"{source}:{preset}" for source, presets in MCP_SOURCE_SCOPE_PRESETS.items() for preset in presets]


def run_query(
    sql: str,
    *,
    team: Team,
    query_type: str,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    placeholders: dict[str, ast.Expr],
    settings: HogQLGlobalSettings,
) -> list[tuple[Any, ...]]:
    response = execute_hogql_query(
        query=sql,
        team=team,
        query_type=query_type,
        placeholders={
            "window_start": ast.Constant(value=utc_bound(window_start)),
            "window_end": ast.Constant(value=utc_bound(window_end)),
            "kept_scopes": _strings(kept_scopes()),
            **placeholders,
        },
        limit_context=LimitContext.SAVED_QUERY,
        workload=etl_workload(),
        settings=settings,
        # The dag runs without a user; the read is a trusted internal ETL over the dogfood project.
        bypass_warehouse_access_control=True,
        ch_user=ClickHouseUser.SIGNALS,
    )
    return [tuple(row) for row in response.results or []]


def input_rows(
    sql: str,
    *,
    team: Team,
    query_type: str,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    distinct_ids: Collection[str],
    projects: Collection[str],
) -> list[tuple[Any, ...]]:
    if not distinct_ids or not projects:
        return []
    return run_query(
        sql,
        team=team,
        query_type=query_type,
        window_start=window_start,
        window_end=window_end,
        placeholders={"distinct_ids": _strings(distinct_ids), "projects": _strings(projects)},
        settings=_INPUT_SETTINGS,
    )


def projection_query_rows(
    sql: str, *, team: Team, query_type: str, window_start: datetime.datetime, window_end: datetime.datetime
) -> list[tuple[Any, ...]]:
    return run_query(
        sql,
        team=team,
        query_type=query_type,
        window_start=window_start,
        window_end=window_end,
        placeholders={
            "plumbing_tools": _strings(PLUMBING_TOOL_NAMES),
            "upkeep_prefixes": ast.Array(exprs=[ast.Constant(value=prefix) for prefix in UPKEEP_TOOL_PREFIXES]),
        },
        settings=_PROJECTION_SETTINGS,
    )
