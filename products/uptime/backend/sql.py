from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

UPTIME_PINGS_TABLE = "uptime_pings"
UPTIME_PINGS_SHARDED_TABLE = f"sharded_{UPTIME_PINGS_TABLE}"

UPTIME_PINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    team_id Int64,
    monitor_id UUID,
    timestamp DateTime64(6, 'UTC'),
    latency_ms UInt32,
    status_code UInt16,
    outcome LowCardinality(String)
) ENGINE = {engine}
"""


def SHARDED_UPTIME_PINGS_TABLE_SQL() -> str:
    return (
        UPTIME_PINGS_TABLE_BASE_SQL
        + """
    PARTITION BY toYYYYMM(timestamp)
    ORDER BY (team_id, monitor_id, timestamp)
    """
    ).format(
        table_name=UPTIME_PINGS_SHARDED_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=MergeTreeEngine(UPTIME_PINGS_SHARDED_TABLE, replication_scheme=ReplicationScheme.SHARDED),
    )


def DISTRIBUTED_UPTIME_PINGS_TABLE_SQL() -> str:
    return UPTIME_PINGS_TABLE_BASE_SQL.format(
        table_name=UPTIME_PINGS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(
            data_table=UPTIME_PINGS_SHARDED_TABLE,
            sharding_key="sipHash64(monitor_id)",
        ),
    )


DROP_UPTIME_PINGS_TABLE_SQL = f"DROP TABLE IF EXISTS {UPTIME_PINGS_TABLE}"
DROP_SHARDED_UPTIME_PINGS_TABLE_SQL = f"DROP TABLE IF EXISTS {UPTIME_PINGS_SHARDED_TABLE} SYNC"
