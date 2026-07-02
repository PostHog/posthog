from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_UPTIME_PINGS, kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_UPTIME_PINGS

UPTIME_PINGS_TABLE = "uptime_pings"
UPTIME_PINGS_SHARDED_TABLE = f"sharded_{UPTIME_PINGS_TABLE}"
UPTIME_PINGS_WRITABLE_TABLE = f"writable_{UPTIME_PINGS_TABLE}"
UPTIME_PINGS_KAFKA_TABLE = f"kafka_{UPTIME_PINGS_TABLE}"
UPTIME_PINGS_MV = f"{UPTIME_PINGS_TABLE}_mv"

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


def WRITABLE_UPTIME_PINGS_TABLE_SQL() -> str:
    """Distributed write target the kafka -> mv pipeline pushes into. Kept separate from the
    read-side distributed table so we can change one without dropping the other."""
    return UPTIME_PINGS_TABLE_BASE_SQL.format(
        table_name=UPTIME_PINGS_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(
            data_table=UPTIME_PINGS_SHARDED_TABLE,
            sharding_key="sipHash64(monitor_id)",
        ),
    )


def KAFKA_UPTIME_PINGS_TABLE_SQL() -> str:
    # `kafka_skip_broken_messages` lets the consumer move past unparseable rows instead of
    # wedging the whole topic on the first bad message. Defensive against format drift
    # between Rust producer and CH parser — without it, a single malformed timestamp at
    # offset N blocks every subsequent message forever.
    return (UPTIME_PINGS_TABLE_BASE_SQL + "SETTINGS kafka_skip_broken_messages = 1000000").format(
        table_name=UPTIME_PINGS_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=kafka_engine(KAFKA_CLICKHOUSE_UPTIME_PINGS, group=CONSUMER_GROUP_UPTIME_PINGS),
    )


def UPTIME_PINGS_MV_SQL(target_table: str = UPTIME_PINGS_WRITABLE_TABLE) -> str:
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
AS SELECT
team_id,
monitor_id,
timestamp,
latency_ms,
status_code,
outcome
FROM {database}.{kafka_table}
""".format(
        mv_name=UPTIME_PINGS_MV,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        target_table=target_table,
        kafka_table=UPTIME_PINGS_KAFKA_TABLE,
        database=settings.CLICKHOUSE_DATABASE,
    )


DROP_UPTIME_PINGS_TABLE_SQL = f"DROP TABLE IF EXISTS {UPTIME_PINGS_TABLE}"
DROP_SHARDED_UPTIME_PINGS_TABLE_SQL = f"DROP TABLE IF EXISTS {UPTIME_PINGS_SHARDED_TABLE} SYNC"
DROP_UPTIME_PINGS_WRITABLE_TABLE_SQL = f"DROP TABLE IF EXISTS {UPTIME_PINGS_WRITABLE_TABLE}"
DROP_UPTIME_PINGS_KAFKA_TABLE_SQL = f"DROP TABLE IF EXISTS {UPTIME_PINGS_KAFKA_TABLE}"
DROP_UPTIME_PINGS_MV_SQL = f"DROP TABLE IF EXISTS {UPTIME_PINGS_MV}"
TRUNCATE_UPTIME_PINGS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {UPTIME_PINGS_SHARDED_TABLE}"
