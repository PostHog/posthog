from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_EMAIL_STATUS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EMAIL_STATUS

EMAIL_STATUS_RETENTION_DAYS = 30
# Parts drop by whole day of `created_at`, so one more day keeps an email created late in a day
# for its full retention.
EMAIL_STATUS_TTL_DAYS = EMAIL_STATUS_RETENTION_DAYS + 1

# AUX-resident table family modelled on `hog_invocation_results`. Each status change of a
# transactional email is one row. A message's rows replace each other by `version`, which puts the
# status rank above the status time, so a late `sent` never replaces `delivered`.
EMAIL_STATUS_TABLE = "email_status"
EMAIL_STATUS_DATA_TABLE = f"{EMAIL_STATUS_TABLE}_data"
KAFKA_EMAIL_STATUS_TABLE = f"kafka_{EMAIL_STATUS_TABLE}"
EMAIL_STATUS_MV_TABLE = f"{EMAIL_STATUS_TABLE}_mv"


EMAIL_STATUS_KAFKA_COLUMNS = """
    team_id Int64,
    message_id UUID,
    status LowCardinality(String),
    version UInt64,
    created_at DateTime64(6, 'UTC'),
    status_at DateTime64(6, 'UTC'),
    reason String
""".strip()


# Every row of a message carries the same `created_at`, so the rows share a partition and the
# ReplacingMergeTree can collapse them.
EMAIL_STATUS_DATA_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {EMAIL_STATUS_DATA_TABLE}
(
    {EMAIL_STATUS_KAFKA_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {ReplacingMergeTree(EMAIL_STATUS_DATA_TABLE, ver="version", replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toYYYYMMDD(created_at)
ORDER BY (team_id, message_id)
{ttl_period("created_at", EMAIL_STATUS_TTL_DAYS, unit="DAY")}
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1
"""
)


# Created on both AUX and DATA, so that queries from either cluster reach the data.
DISTRIBUTED_EMAIL_STATUS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {EMAIL_STATUS_TABLE}
(
    {EMAIL_STATUS_KAFKA_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=EMAIL_STATUS_DATA_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER)}
"""
)


# The CDP producer writes to the cyclotron WarpStream cluster, so the Kafka table reads from its
# named collection.
KAFKA_EMAIL_STATUS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {KAFKA_EMAIL_STATUS_TABLE}
(
    {EMAIL_STATUS_KAFKA_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_EMAIL_STATUS,
            group=CONSUMER_GROUP_EMAIL_STATUS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_CYCLOTRON_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100,
         kafka_num_consumers = 1,
         kafka_thread_per_consumer = 1,
         kafka_poll_timeout_ms = 10000,
         kafka_max_block_size = 100000
"""
)


EMAIL_STATUS_MV_SQL = lambda: (
    f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {EMAIL_STATUS_MV_TABLE}
TO {EMAIL_STATUS_DATA_TABLE}
AS SELECT
    team_id,
    message_id,
    status,
    version,
    created_at,
    status_at,
    reason,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_EMAIL_STATUS_TABLE}
"""
)
