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
    calls_in_run UInt32, -- calls carrying this intent in the assignment window
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
