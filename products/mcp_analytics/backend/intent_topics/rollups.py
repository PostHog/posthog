"""Rollup writes: hourly calls per intent (from the sync run) and daily calls per topic (from the assign run)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from posthog.clickhouse.client import sync_execute

from products.mcp_analytics.backend.facade.clickhouse_schema import (
    MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
    MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE,
    MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE,
    MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE,
)
from products.mcp_analytics.backend.intent_topics.corpus import HourlyCalls

INSERT_BATCH_SIZE = 10_000


def insert_hourly_calls(team_id: int, rows: Sequence[HourlyCalls], *, now: datetime) -> int:
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start : start + INSERT_BATCH_SIZE]
        sync_execute(
            f"INSERT INTO {MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE} (team_id, hour, intent_hash, tool, calls, sessions, inserted_at) VALUES",
            [(team_id, row.hour, row.hash, row.tool, row.calls, row.sessions, now) for row in batch],
        )
    return len(rows)


# The assignments side is restricted to the window's hashes before the join, so the in-memory
# right side is the day's distinct intents, never the whole team history.
_TOPIC_DAILY_INSERT_SQL = """
INSERT INTO {target_table} (team_id, day, tool, topic_id, calls, sessions, outlier_calls, intents, inserted_at)
SELECT
    %(team_id)s AS team_id,
    toDate(c.hour) AS day,
    c.tool AS tool,
    coalesce(a.topic_id, '') AS topic_id,
    sum(c.calls) AS calls,
    sum(c.sessions) AS sessions,
    sumIf(c.calls, a.is_outlier = 1) AS outlier_calls,
    uniqExact(c.intent_hash) AS intents,
    now64(3) AS inserted_at
FROM {calls_table} AS c
LEFT JOIN (
    SELECT intent_hash, argMax(topic_id, timestamp) AS topic_id, argMax(is_outlier, timestamp) AS is_outlier
    FROM {assignments_table}
    WHERE team_id = %(team_id)s
      AND intent_hash IN (
          SELECT DISTINCT intent_hash FROM {calls_table}
          WHERE team_id = %(team_id)s AND hour >= %(window_start)s AND hour < %(window_end)s
      )
    GROUP BY intent_hash
) AS a ON c.intent_hash = a.intent_hash
WHERE c.team_id = %(team_id)s
  AND c.hour >= %(window_start)s
  AND c.hour < %(window_end)s
GROUP BY day, tool, topic_id
"""


def build_topic_daily_insert(
    *, team_id: int, window_start: datetime, window_end: datetime
) -> tuple[str, dict[str, Any]]:
    sql = _TOPIC_DAILY_INSERT_SQL.format(
        target_table=MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE,
        calls_table=MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE,
        assignments_table=MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
    )
    return sql, {"team_id": team_id, "window_start": window_start, "window_end": window_end}


def rebuild_topic_daily(*, team_id: int, window_start: datetime, window_end: datetime) -> None:
    sql, params = build_topic_daily_insert(team_id=team_id, window_start=window_start, window_end=window_end)
    sync_execute(sql, params)
