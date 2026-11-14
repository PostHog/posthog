"""Rollups: hourly calls per intent (written by the sync run) and daily calls per topic (written by the assign run).

Both tables are ReplacingMergeTree, which keeps every version of a row until parts merge, so every
reader goes through ``hourly_calls_source`` or ``topic_daily_source`` to see one version only.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client import sync_execute

from products.mcp_analytics.backend.facade.clickhouse_schema import (
    MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
    MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE,
    MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE,
    MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE,
)
from products.mcp_analytics.backend.intent_topics.corpus import HourlyCalls

INSERT_BATCH_SIZE = 10_000

_HOURLY_INSERT_SQL = (
    "INSERT INTO "
    + MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE
    + " (team_id, hour, intent_hash, tool, calls, conversation_hashes, inserted_at) VALUES"
)


def insert_hourly_calls(team_id: int, rows: Sequence[HourlyCalls], *, now: datetime) -> int:
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start : start + INSERT_BATCH_SIZE]
        sync_execute(
            _HOURLY_INSERT_SQL,
            [(team_id, row.hour, row.hash, row.tool, row.calls, list(row.conversations), now) for row in batch],
        )
    return len(rows)


# The latest version of each hourly bucket, joined to the latest assignment of each intent. The
# assignments side is restricted to the window's hashes before the join, so the in-memory right
# side is the window's distinct intents, never the whole team history.
_TOPIC_DAILY_INSERT_SQL = """
INSERT INTO {target_table} (team_id, day, tool, topic_id, calls, conversation_hashes, outlier_calls, intents, inserted_at)
SELECT
    %(team_id)s AS team_id,
    toDate(c.hour) AS day,
    c.tool AS tool,
    coalesce(a.topic_id, '') AS topic_id,
    sum(c.calls) AS calls,
    arraySort(groupUniqArrayArray(c.conversation_hashes)) AS conversation_hashes,
    sumIf(c.calls, a.is_outlier = 1) AS outlier_calls,
    uniqExact(c.intent_hash) AS intents,
    toDateTime64(%(inserted_at)s, 6, 'UTC') AS inserted_at
FROM (
    SELECT hour, intent_hash, tool,
           argMax(calls, inserted_at) AS calls,
           argMax(conversation_hashes, inserted_at) AS conversation_hashes
    FROM {calls_table}
    WHERE team_id = %(team_id)s AND hour >= %(day_start)s AND hour < %(day_end)s
    GROUP BY hour, intent_hash, tool
) AS c
LEFT JOIN (
    SELECT intent_hash,
           argMax(ifNull(topic_id, ''), timestamp) AS topic_id,
           argMax(is_outlier, timestamp) AS is_outlier
    FROM {assignments_table}
    WHERE team_id = %(team_id)s
      AND intent_hash IN (
          SELECT DISTINCT intent_hash FROM {calls_table}
          WHERE team_id = %(team_id)s AND hour >= %(day_start)s AND hour < %(day_end)s
      )
    GROUP BY intent_hash
) AS a ON c.intent_hash = a.intent_hash
GROUP BY day, tool, topic_id
"""


@dataclass(frozen=True)
class WholeDays:
    """[start, end) widened to midnight on both sides."""

    start: datetime
    end: datetime

    @classmethod
    def covering(cls, window_start: datetime, window_end: datetime) -> "WholeDays":
        start = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = window_end.replace(hour=0, minute=0, second=0, microsecond=0)
        if end < window_end:
            end += timedelta(days=1)
        return cls(start=start, end=end)


def build_topic_daily_insert(
    *, team_id: int, window_start: datetime, window_end: datetime, now: datetime
) -> tuple[str, dict[str, Any]]:
    """Rebuild every day the window touches from its first hour to its last.

    A partial day would replace a complete one, and every row of one rebuild shares ``inserted_at``, so a
    reader that keeps the latest rebuild per day drops topics that lost all their intents to another topic.
    """
    days = WholeDays.covering(window_start, window_end)
    sql = _TOPIC_DAILY_INSERT_SQL.format(
        target_table=MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE,
        calls_table=MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE,
        assignments_table=MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
    )
    # Passed as text: a datetime parameter loses everything below the second, and two rebuilds in one
    # second would then share a version.
    inserted_at = now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    return sql, {"team_id": team_id, "day_start": days.start, "day_end": days.end, "inserted_at": inserted_at}


def rebuild_topic_daily(*, team_id: int, window_start: datetime, window_end: datetime, now: datetime) -> None:
    sql, params = build_topic_daily_insert(team_id=team_id, window_start=window_start, window_end=window_end, now=now)
    sync_execute(sql, params)


_HOURLY_SOURCE_SQL = """
SELECT hour, intent_hash, tool,
       argMax(calls, inserted_at) AS calls,
       argMax(conversation_hashes, inserted_at) AS conversation_hashes
FROM posthog.mcp_intent_calls_hourly
WHERE hour >= {since} AND hour < {until} AND {tool_filter}
GROUP BY hour, intent_hash, tool
"""


def hourly_calls_source(*, since: datetime, until: datetime, tool: str | None = None) -> ast.SelectQuery:
    """One row per (hour, intent, tool) in [since, until): the latest version written by the sync runs."""
    return cast(
        ast.SelectQuery,
        parse_select(
            _HOURLY_SOURCE_SQL,
            placeholders={
                "since": ast.Constant(value=since),
                "until": ast.Constant(value=until),
                "tool_filter": _tool_filter(tool),
            },
        ),
    )


_DAILY_SOURCE_SQL = """
SELECT day, tool, topic_id, calls, conversation_hashes, outlier_calls, intents
FROM posthog.mcp_intent_topic_daily
WHERE day >= {day_from} AND day <= {day_to} AND {tool_filter}
  AND (day, inserted_at) IN (
      SELECT day, max(inserted_at)
      FROM posthog.mcp_intent_topic_daily
      WHERE day >= {day_from} AND day <= {day_to}
      GROUP BY day
  )
"""


def topic_daily_source(*, day_from: datetime, day_to: datetime, tool: str | None = None) -> ast.SelectQuery:
    """Rows of the latest rebuild of each day in [day_from, day_to], both days inclusive."""
    return cast(
        ast.SelectQuery,
        parse_select(
            _DAILY_SOURCE_SQL,
            placeholders={
                "day_from": ast.Constant(value=day_from.date()),
                "day_to": ast.Constant(value=day_to.date()),
                "tool_filter": _tool_filter(tool),
            },
        ),
    )


def _tool_filter(tool: str | None) -> ast.Expr:
    if not tool:
        return ast.Constant(value=True)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["tool"]), right=ast.Constant(value=tool)
    )
