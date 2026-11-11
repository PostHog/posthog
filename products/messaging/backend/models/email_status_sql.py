from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_EMAIL_STATUS,
    CONSUMER_GROUP_EMAIL_STATUS_EVENTS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplacingMergeTree, ReplicationScheme
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

# Keeps every status row of a message, where `email_status` keeps only the latest. The email log reads
# the timeline, the opens and clicks, and the recipient and sending domain from it.
EMAIL_STATUS_EVENTS_TABLE = "email_status_events"
EMAIL_STATUS_EVENTS_DATA_TABLE = f"{EMAIL_STATUS_EVENTS_TABLE}_data"
EMAIL_STATUS_EVENTS_MV_TABLE = f"{EMAIL_STATUS_EVENTS_TABLE}_mv"
# Its own Kafka table and consumer group on the same topic, so adding it leaves the `email_status` feed untouched.
KAFKA_EMAIL_STATUS_EVENTS_TABLE = f"kafka_{EMAIL_STATUS_EVENTS_TABLE}"

# Rows that record what the recipient did with the email. They never change its delivery status.
EMAIL_ENGAGEMENT_STATUSES = ("opened", "clicked")


EMAIL_STATUS_KAFKA_COLUMNS = """
    team_id Int64,
    message_id UUID,
    status LowCardinality(String),
    version UInt64,
    created_at DateTime64(6, 'UTC'),
    status_at DateTime64(6, 'UTC'),
    reason String
""".strip()

# The queued row carries the recipient and the workflow, and the sent row the sending domain. Other rows
# leave them empty.
EMAIL_STATUS_EVENTS_KAFKA_COLUMNS = f"""
    {EMAIL_STATUS_KAFKA_COLUMNS},
    recipient String,
    function_id String,
    sending_domain LowCardinality(String)
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


def _kafka_email_status_table_sql(table: str, columns: str, group: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table}
(
    {columns}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_EMAIL_STATUS,
            group=group,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_CYCLOTRON_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100,
         kafka_num_consumers = 1,
         kafka_thread_per_consumer = 1,
         kafka_poll_timeout_ms = 10000,
         kafka_max_block_size = 100000
"""


# The CDP producer writes to the cyclotron WarpStream cluster, so the Kafka tables read from its
# named collection.
KAFKA_EMAIL_STATUS_TABLE_SQL = lambda: _kafka_email_status_table_sql(
    KAFKA_EMAIL_STATUS_TABLE, EMAIL_STATUS_KAFKA_COLUMNS, CONSUMER_GROUP_EMAIL_STATUS
)

KAFKA_EMAIL_STATUS_EVENTS_TABLE_SQL = lambda: _kafka_email_status_table_sql(
    KAFKA_EMAIL_STATUS_EVENTS_TABLE, EMAIL_STATUS_EVENTS_KAFKA_COLUMNS, CONSUMER_GROUP_EMAIL_STATUS_EVENTS
)


# Opens and clicks rank above delivered, so in this ReplacingMergeTree they would replace the delivery status.
EMAIL_STATUS_MV_QUERY = lambda: (
    f"""
SELECT
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
WHERE status NOT IN {EMAIL_ENGAGEMENT_STATUSES}
"""
)

EMAIL_STATUS_MV_SQL = lambda: (
    f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {EMAIL_STATUS_MV_TABLE}
TO {EMAIL_STATUS_DATA_TABLE}
AS {EMAIL_STATUS_MV_QUERY()}"""
)

# Changes the query of an existing view in place, so it keeps consuming with no gap.
ALTER_EMAIL_STATUS_MV_QUERY_SQL = lambda: f"ALTER TABLE {EMAIL_STATUS_MV_TABLE} MODIFY QUERY {EMAIL_STATUS_MV_QUERY()}"


# A plain MergeTree, so no row replaces another. `created_at` leads the key because ClickHouse doesn't sort a
# UUID by time. All rows of a message share a `created_at`, so they stay together.
EMAIL_STATUS_EVENTS_DATA_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {EMAIL_STATUS_EVENTS_DATA_TABLE}
(
    {EMAIL_STATUS_EVENTS_KAFKA_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {MergeTreeEngine(EMAIL_STATUS_EVENTS_DATA_TABLE, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toYYYYMMDD(created_at)
ORDER BY (team_id, created_at, message_id, status_at)
{ttl_period("created_at", EMAIL_STATUS_TTL_DAYS, unit="DAY")}
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1
"""
)


DISTRIBUTED_EMAIL_STATUS_EVENTS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {EMAIL_STATUS_EVENTS_TABLE}
(
    {EMAIL_STATUS_EVENTS_KAFKA_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=EMAIL_STATUS_EVENTS_DATA_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER)}
"""
)


EMAIL_STATUS_EVENTS_MV_SQL = lambda: (
    f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {EMAIL_STATUS_EVENTS_MV_TABLE}
TO {EMAIL_STATUS_EVENTS_DATA_TABLE}
AS SELECT
    team_id,
    message_id,
    status,
    version,
    created_at,
    status_at,
    reason,
    recipient,
    function_id,
    sending_domain,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_EMAIL_STATUS_EVENTS_TABLE}
"""
)
