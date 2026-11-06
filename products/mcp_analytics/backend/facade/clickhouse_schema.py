"""ClickHouse DDL for `mcp_intent_assignments`.

One row per (team, intent text hash) holding the topic the latest run assigned it to, the cosine
distance to that topic's centroid, a 2D position for the intent map and the intent text itself.
Rows live for three months so trend questions can span a quarter without the vectors, which the
`text-embedding-3-small-256` embedding table only keeps for one month.

Exported through the facade because core ClickHouse migrations import product DDL, as they do for
`products.error_tracking.backend.indexed_embedding`.
"""

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

MCP_INTENT_ASSIGNMENTS_DATA_TABLE = "sharded_mcp_intent_assignments"
MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE = "distributed_mcp_intent_assignments"
MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE = "writable_mcp_intent_assignments"

_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    intent_hash String, -- sha256 hex of the raw $mcp_intent text, see intent_hash.py
    run_id String, -- pipeline run that wrote the row
    topic_id Nullable(String), -- MCPIntentTopic id; NULL when no topic was within reach
    distance Float32, -- cosine distance to the assigned topic centroid
    x Float32, -- 2D map position
    y Float32,
    is_outlier UInt8,
    intent_text String, -- truncated copy for the map and outlier lists
    calls_in_run UInt32, -- calls carrying this intent when it was embedded
    timestamp DateTime64(3, 'UTC') -- when the assignment was made; newest wins
) ENGINE = {engine}
"""

_SHARDED_SQL = (
    _BASE_SQL
    + """
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (team_id, intent_hash)
    TTL toDateTime(timestamp) + INTERVAL 3 MONTH
    SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""
)


def MCP_INTENT_ASSIGNMENTS_DATA_TABLE_ENGINE() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        MCP_INTENT_ASSIGNMENTS_DATA_TABLE, ver="timestamp", replication_scheme=ReplicationScheme.SHARDED
    )


def MCP_INTENT_ASSIGNMENTS_DATA_TABLE_SQL() -> str:
    return _SHARDED_SQL.format(
        table_name=MCP_INTENT_ASSIGNMENTS_DATA_TABLE,
        engine=MCP_INTENT_ASSIGNMENTS_DATA_TABLE_ENGINE(),
    )


def MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE_SQL() -> str:
    return _BASE_SQL.format(
        table_name=MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE,
        engine=Distributed(
            data_table=MCP_INTENT_ASSIGNMENTS_DATA_TABLE,
            sharding_key="cityHash64(intent_hash)",
            cluster=settings.CLICKHOUSE_CLUSTER,
        ),
    )


def MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE_SQL() -> str:
    return _BASE_SQL.format(
        table_name=MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE,
        engine=Distributed(
            data_table=MCP_INTENT_ASSIGNMENTS_DATA_TABLE,
            sharding_key="cityHash64(intent_hash)",
            cluster=settings.CLICKHOUSE_CLUSTER,
        ),
    )


def DROP_MCP_INTENT_ASSIGNMENTS_TABLES_SQL() -> list[str]:
    return [
        f"DROP TABLE IF EXISTS {MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE}",
        f"DROP TABLE IF EXISTS {MCP_INTENT_ASSIGNMENTS_DISTRIBUTED_TABLE}",
        f"DROP TABLE IF EXISTS {MCP_INTENT_ASSIGNMENTS_DATA_TABLE}",
    ]


# Hourly call counts per intent text and tool, written by the sync run for every distinct intent in
# its window (seen or not). The topic rollup joins these to the assignments by hash, so no query
# ever joins the events table to the assignments.
MCP_INTENT_CALLS_HOURLY_DATA_TABLE = "sharded_mcp_intent_calls_hourly"
MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE = "distributed_mcp_intent_calls_hourly"
MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE = "writable_mcp_intent_calls_hourly"

_CALLS_HOURLY_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    hour DateTime('UTC'),
    intent_hash String,
    tool LowCardinality(String),
    calls UInt32,
    conversation_hashes Array(UInt64), -- cityHash64 of each distinct conversation id
    inserted_at DateTime64(3, 'UTC')
) ENGINE = {engine}
"""

_CALLS_HOURLY_SHARDED_SQL = (
    _CALLS_HOURLY_BASE_SQL
    + """
    PARTITION BY toYYYYMM(hour)
    ORDER BY (team_id, hour, intent_hash, tool)
    TTL hour + INTERVAL 6 MONTH
    SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""
)


def MCP_INTENT_CALLS_HOURLY_DATA_TABLE_SQL() -> str:
    return _CALLS_HOURLY_SHARDED_SQL.format(
        table_name=MCP_INTENT_CALLS_HOURLY_DATA_TABLE,
        engine=ReplacingMergeTree(
            MCP_INTENT_CALLS_HOURLY_DATA_TABLE, ver="inserted_at", replication_scheme=ReplicationScheme.SHARDED
        ),
    )


def MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE_SQL() -> str:
    return _CALLS_HOURLY_BASE_SQL.format(
        table_name=MCP_INTENT_CALLS_HOURLY_DISTRIBUTED_TABLE,
        engine=Distributed(
            data_table=MCP_INTENT_CALLS_HOURLY_DATA_TABLE,
            sharding_key="cityHash64(intent_hash)",
            cluster=settings.CLICKHOUSE_CLUSTER,
        ),
    )


def MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE_SQL() -> str:
    return _CALLS_HOURLY_BASE_SQL.format(
        table_name=MCP_INTENT_CALLS_HOURLY_WRITABLE_TABLE,
        engine=Distributed(
            data_table=MCP_INTENT_CALLS_HOURLY_DATA_TABLE,
            sharding_key="cityHash64(intent_hash)",
            cluster=settings.CLICKHOUSE_CLUSTER,
        ),
    )


# Daily rollup per tool and topic, rebuilt one whole day at a time by the assignment run. This is what
# the intent topic queries read: a few thousand rows per team per day instead of millions of events.
MCP_INTENT_TOPIC_DAILY_DATA_TABLE = "sharded_mcp_intent_topic_daily"
MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE = "distributed_mcp_intent_topic_daily"
MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE = "writable_mcp_intent_topic_daily"

_TOPIC_DAILY_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    day Date,
    tool LowCardinality(String),
    topic_id String, -- '' when the intent had no topic yet
    calls UInt64,
    conversation_hashes Array(UInt64), -- distinct conversations, kept as hashes so readers can union days and tools
    outlier_calls UInt64,
    intents UInt64, -- distinct intent texts
    inserted_at DateTime64(6, 'UTC') -- one value per rebuild; readers keep only the latest rebuild of each day
) ENGINE = {engine}
"""

_TOPIC_DAILY_SHARDED_SQL = (
    _TOPIC_DAILY_BASE_SQL
    + """
    PARTITION BY toYYYYMM(day)
    ORDER BY (team_id, day, tool, topic_id)
    TTL day + INTERVAL 12 MONTH
    SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""
)


def MCP_INTENT_TOPIC_DAILY_DATA_TABLE_SQL() -> str:
    return _TOPIC_DAILY_SHARDED_SQL.format(
        table_name=MCP_INTENT_TOPIC_DAILY_DATA_TABLE,
        engine=ReplacingMergeTree(
            MCP_INTENT_TOPIC_DAILY_DATA_TABLE, ver="inserted_at", replication_scheme=ReplicationScheme.SHARDED
        ),
    )


def MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE_SQL() -> str:
    return _TOPIC_DAILY_BASE_SQL.format(
        table_name=MCP_INTENT_TOPIC_DAILY_DISTRIBUTED_TABLE,
        engine=Distributed(
            data_table=MCP_INTENT_TOPIC_DAILY_DATA_TABLE,
            sharding_key="cityHash64(team_id)",
            cluster=settings.CLICKHOUSE_CLUSTER,
        ),
    )


def MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE_SQL() -> str:
    return _TOPIC_DAILY_BASE_SQL.format(
        table_name=MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE,
        engine=Distributed(
            data_table=MCP_INTENT_TOPIC_DAILY_DATA_TABLE,
            sharding_key="cityHash64(team_id)",
            cluster=settings.CLICKHOUSE_CLUSTER,
        ),
    )
