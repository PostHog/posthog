from django.conf import settings

from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_AGENT_EVENTS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
)
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_AGENT_EVENTS

AGENT_LOGS_TABLE = "agent_logs"
AGENT_LOGS_WRITABLE_TABLE = f"writable_{AGENT_LOGS_TABLE}"
KAFKA_AGENT_LOGS_TABLE = f"kafka_{AGENT_LOGS_TABLE}"
AGENT_LOGS_MV = f"{AGENT_LOGS_TABLE}_mv"

DROP_AGENT_LOGS_MV_SQL = f"DROP TABLE IF EXISTS {AGENT_LOGS_MV}"
DROP_KAFKA_AGENT_LOGS_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_AGENT_LOGS_TABLE}"

AGENT_LOGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    task_id UUID,
    run_id UUID,
    sequence UInt64,
    timestamp DateTime64(3, 'UTC'),
    entry_type LowCardinality(String),
    entry String CODEC(ZSTD(3))
    {extra_fields}
) ENGINE = {engine}
"""


def AGENT_LOGS_TABLE_ENGINE():
    return MergeTreeEngine(AGENT_LOGS_TABLE, replication_scheme=ReplicationScheme.REPLICATED)


def AGENT_LOGS_DATA_TABLE_SQL():
    return (
        AGENT_LOGS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, task_id, run_id, sequence)
TTL toDate(timestamp) + INTERVAL 90 DAY
SETTINGS index_granularity = 512
"""
    ).format(
        table_name=AGENT_LOGS_TABLE,
        engine=AGENT_LOGS_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(AGENT_LOGS_TABLE)}
    """,
    )


def AGENT_LOGS_WRITABLE_TABLE_SQL():
    return AGENT_LOGS_TABLE_BASE_SQL.format(
        table_name=AGENT_LOGS_WRITABLE_TABLE,
        engine=Distributed(
            data_table=AGENT_LOGS_TABLE,
            cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )


def KAFKA_AGENT_LOGS_TABLE_SQL():
    return AGENT_LOGS_TABLE_BASE_SQL.format(
        table_name=KAFKA_AGENT_LOGS_TABLE,
        engine=kafka_engine(KAFKA_AGENT_EVENTS, group=CONSUMER_GROUP_AGENT_EVENTS),
        extra_fields="",
    )


def AGENT_LOGS_MV_SQL(target_table=AGENT_LOGS_WRITABLE_TABLE):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
team_id,
task_id,
run_id,
sequence,
timestamp,
entry_type,
entry,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
""".format(
        mv_name=AGENT_LOGS_MV,
        target_table=target_table,
        kafka_table=KAFKA_AGENT_LOGS_TABLE,
        database=settings.CLICKHOUSE_DATABASE,
    )
