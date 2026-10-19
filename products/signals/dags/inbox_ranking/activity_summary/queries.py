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
    CHAIN_SEPARATOR,
    MAX_CHAIN_INTENTS,
    MAX_PROMPT_CHARS,
    MIN_CHAIN_INTENTS,
    PLUMBING_TOOL_NAMES,
)
from products.signals.dags.inbox_ranking.dataset.queries import etl_workload, utc_bound

# Each kept MCP source, with the scope presets that mark a person's own calls ("" is no preset).
# Scouts, research and implementation runs carry other presets and are not a person's intent.
# A Slack call runs in the Slack app's sandbox for the person who wrote the message, so it carries
# `sandbox` and never `user`. Keeping only `user` here would drop every Slack call.
MCP_SOURCE_SCOPE_PRESETS: dict[str, tuple[str, ...]] = {
    "mcp": ("user", ""),
    "slack": ("sandbox",),
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

_AI_FILTERS = """
    event = 'chat with ai'
    AND timestamp >= toDateTime({window_start}) AND timestamp < toDateTime({window_end})
    AND toString(properties.is_new_conversation) = 'true'
    AND nullIf(toString(properties.prompt), '') IS NOT NULL
    AND nullIf($group_2, '') IS NOT NULL
"""

# One row per session with its calls as parallel arrays. groupArray walks the rows in one order for
# every array, so index i of each array is the same call. render.py sorts and filters them.
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
"""

INPUT_AI_PROMPTS_SQL = f"""
SELECT
    distinct_id,
    $group_2 AS project,
    toTimeZone(timestamp, 'UTC') AS prompted_at,
    toString(properties.prompt) AS prompt
FROM events
WHERE {_AI_FILTERS}
  AND distinct_id IN {{distinct_ids}}
  AND $group_2 IN {{projects}}
"""

# The projection approximates render.py in SQL, and these filters do not run here:
# - the repeated-job filter and the dedupe of identical chains and prompts, so units are overcounted
#   for people with scheduled jobs;
# - secret stripping and whitespace folding, which change lengths very little;
# - the consecutive-repeat collapse, approximated by distinct intents per session. That undercounts a
#   chain that comes back to an earlier intent.
# The pair is (project, distinct_id), not (project, person): a person with several distinct ids is
# counted more than once. The calibration ratio against the inputs asset absorbs the length error.
PROJECTION_MCP_SQL = f"""
SELECT
    distinct_id,
    project,
    countIf(distinct_intents >= {MIN_CHAIN_INTENTS}) AS mcp_sessions,
    sumIf(chain_chars, distinct_intents >= {MIN_CHAIN_INTENTS}) AS mcp_chain_chars
FROM (
    SELECT
        distinct_id,
        $group_2 AS project,
        {_SESSION_KEY} AS session_key,
        uniqIf(toString(properties.$mcp_intent), ifNull(toString(properties.$mcp_tool_name), '') NOT IN {{plumbing_tools}}) AS distinct_intents,
        least(distinct_intents, {MAX_CHAIN_INTENTS}) AS kept_intents,
        kept_intents * avgIf(length(toString(properties.$mcp_intent)), ifNull(toString(properties.$mcp_tool_name), '') NOT IN {{plumbing_tools}})
            + (kept_intents - 1) * {len(CHAIN_SEPARATOR)} AS chain_chars
    FROM events
    WHERE {_MCP_FILTERS}
    GROUP BY distinct_id, project, session_key
)
GROUP BY distinct_id, project
HAVING mcp_sessions > 0
"""

PROJECTION_AI_SQL = f"""
SELECT
    distinct_id,
    $group_2 AS project,
    count() AS ai_conversations,
    sum(least(length(toString(properties.prompt)), {MAX_PROMPT_CHARS})) AS ai_prompt_chars
FROM events
WHERE {_AI_FILTERS}
GROUP BY distinct_id, project
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
        placeholders={"plumbing_tools": _strings(PLUMBING_TOOL_NAMES)},
        settings=_PROJECTION_SETTINGS,
    )
