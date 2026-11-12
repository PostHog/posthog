from django.conf import settings

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS,
    CONSUMER_GROUP_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS,
    CONSUMER_GROUP_ERROR_TRACKING_ISSUE_TAGS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    kafka_num_consumers,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree
from posthog.kafka_client.topics import (
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS,
    KAFKA_ERROR_TRACKING_ISSUE_TAGS,
)

#
# error_tracking_issue_fingerprint_overrides: This table contains rows for all (team_id, fingerprint)
# pairs where the $exception_issue_id has changed.
#

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE = "error_tracking_issue_fingerprint_overrides"
ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WRITABLE_TABLE = (
    f"writable_{ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE}"
)
ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_SHARDED_TABLE = f"sharded_{ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE}"
ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_KAFKA_TABLE = f"kafka_{ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE}"
ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_MV = f"{ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE}_mv"

DROP_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_MV_SQL = (
    f"DROP TABLE IF EXISTS {ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_MV}"
)
DROP_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_KAFKA_TABLE_SQL = (
    f"DROP TABLE IF EXISTS {ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_KAFKA_TABLE}"
)

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    is_deleted Int8,
    version Int64
    {extra_fields}
) ENGINE = {engine}
"""

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_ENGINE = lambda: ReplacingMergeTree(
    ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE, ver="version"
)

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL = lambda on_cluster=True: (
    ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_BASE_SQL
    + """
    ORDER BY (team_id, fingerprint)
    SETTINGS index_granularity = 512
    """
).format(
    table_name=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE,
    on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    engine=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_ENGINE(),
    extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE)}
    """,
)

KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL = lambda on_cluster=True: (
    ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_BASE_SQL.format(
        table_name=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(
            KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT, group="clickhouse-error-tracking-issue-fingerprint-overrides"
        ),
        extra_fields="",
    )
)


def ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_MV_SQL(
    on_cluster=True, target_table=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WRITABLE_TABLE
):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
AS SELECT
team_id,
fingerprint,
issue_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
WHERE version > 0 -- only store updated rows, not newly inserted ones
""".format(
        mv_name=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_MV,
        target_table=target_table,
        kafka_table=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        database=settings.CLICKHOUSE_DATABASE,
    )


WRITABLE_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL = lambda: (
    ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_BASE_SQL.format(
        table_name=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(
            data_table=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE,
            cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )
)


def TRUNCATE_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE} {ON_CLUSTER_CLAUSE()}"


def TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE}"


INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES = """
INSERT INTO error_tracking_issue_fingerprint_overrides (fingerprint, issue_id, team_id, is_deleted, version, _timestamp, _offset, _partition) SELECT %(fingerprint)s, %(issue_id)s, %(team_id)s, %(is_deleted)s, %(version)s, now(), 0, 0 VALUES
"""

# WarpStream-shared Kafka engine table + MV for error_tracking_issue_fingerprint_overrides.
# Coexists with the MSK-pointed table during cut-over; the MSK side gets dropped in a follow-up
# migration once produce traffic has fully shifted to warpstream-shared.

ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_KAFKA_TABLE = (
    f"kafka_{ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE}_ws"
)
ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_MV = f"{ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE}_ws_mv"

DROP_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_KAFKA_TABLE_SQL = (
    f"DROP TABLE IF EXISTS {ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_KAFKA_TABLE}"
)
DROP_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_MV_SQL = (
    f"DROP TABLE IF EXISTS {ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_MV}"
)


def KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_TABLE_SQL(on_cluster=False):
    return ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_BASE_SQL.format(
        table_name=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(
            KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT,
            group=CONSUMER_GROUP_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_SHARED_NAMED_COLLECTION,
        ),
        extra_fields="",
    )


def ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_MV_SQL(
    on_cluster=False, target_table=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WRITABLE_TABLE
):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
AS SELECT
team_id,
fingerprint,
issue_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
WHERE version > 0 -- only store updated rows, not newly inserted ones
""".format(
        mv_name=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_MV,
        target_table=target_table,
        kafka_table=ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_WS_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        database=settings.CLICKHOUSE_DATABASE,
    )


#
# error_tracking_fingerprint_issue_state: Contains issue metadata alongside fingerprint
# mappings, eliminating the need for Postgres JOINs in the list query.
#

ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE = "error_tracking_fingerprint_issue_state"
ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE = f"raw_{ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE}"
ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WRITABLE_TABLE = f"writable_{ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE}"
ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_KAFKA_TABLE = f"kafka_{ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE}"
ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_MV = f"{ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE}_mv"

ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    issue_name Nullable(VARCHAR),
    issue_description Nullable(VARCHAR),
    issue_status VARCHAR,
    issue_severity Nullable(VARCHAR),
    assigned_user_id Nullable(Int64),
    assigned_role_id Nullable(UUID),
    first_seen DateTime64(3, 'UTC'),
    is_deleted Int8,
    version Int64
    {extra_fields}
) ENGINE = {engine}
"""

ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE_ENGINE = lambda: ReplacingMergeTree(
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE, ver="version"
)


def RAW_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL():
    return (
        ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_BASE_SQL
        + """
    ORDER BY (team_id, fingerprint)
    SETTINGS index_granularity = 512
    """
    ).format(
        table_name=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE)}
    """,
    )


def KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL():
    return ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_BASE_SQL.format(
        table_name=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=kafka_engine(
            KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
            group="clickhouse-error-tracking-fingerprint-issue-state",
        ),
        extra_fields="",
    )


def ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_MV_SQL(
    target_table=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WRITABLE_TABLE,
):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
AS SELECT
team_id,
fingerprint,
issue_id,
issue_name,
issue_description,
issue_status,
issue_severity,
assigned_user_id,
assigned_role_id,
first_seen,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
""".format(
        mv_name=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_MV,
        target_table=target_table,
        kafka_table=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        database=settings.CLICKHOUSE_DATABASE,
    )


WRITABLE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL = lambda: (
    ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_BASE_SQL.format(
        table_name=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(
            data_table=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE,
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )
)

ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL = lambda: ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_BASE_SQL.format(
    table_name=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE,
    on_cluster_clause=ON_CLUSTER_CLAUSE(False),
    engine=Distributed(
        data_table=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_RAW_TABLE,
        cluster=settings.CLICKHOUSE_AUX_CLUSTER,
    ),
    extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
)


INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE = """
INSERT INTO error_tracking_fingerprint_issue_state (fingerprint, issue_id, team_id, issue_name, issue_description, issue_status, issue_severity, assigned_user_id, assigned_role_id, first_seen, is_deleted, version, _timestamp, _offset, _partition) SELECT %(fingerprint)s, %(issue_id)s, %(team_id)s, %(issue_name)s, %(issue_description)s, %(issue_status)s, %(issue_severity)s, %(assigned_user_id)s, %(assigned_role_id)s, %(first_seen)s, %(is_deleted)s, %(version)s, now(), 0, 0 VALUES
"""

# WarpStream-shared Kafka engine table + MV for error_tracking_fingerprint_issue_state.
# Coexists with the MSK-pointed table during cut-over.

ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE = f"kafka_{ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE}_ws"
ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV = f"{ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE}_ws_mv"

DROP_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE_SQL = (
    f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE}"
)
DROP_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL = (
    f"DROP TABLE IF EXISTS {ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV}"
)


def KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_TABLE_SQL():
    return ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_BASE_SQL.format(
        table_name=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=kafka_engine(
            KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
            group=CONSUMER_GROUP_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_SHARED_NAMED_COLLECTION,
        ),
        extra_fields="",
    )


def ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV_SQL(
    target_table=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WRITABLE_TABLE,
):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
AS SELECT
team_id,
fingerprint,
issue_id,
issue_name,
issue_description,
issue_status,
issue_severity,
assigned_user_id,
assigned_role_id,
first_seen,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
""".format(
        mv_name=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_MV,
        target_table=target_table,
        kafka_table=ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_WS_KAFKA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        database=settings.CLICKHOUSE_DATABASE,
    )


#
# error_tracking_issue_tags: The answers to issue tag questions. Each write adds a row. The row with the highest
# version for a (team_id, key, issue_id) is the current answer, and a merge drops the older rows.
# The answers have their own table because cymbal writes complete rows to error_tracking_fingerprint_issue_state,
# and each cymbal write would reset a tags column there. Django is the only writer of this table.
#

ERROR_TRACKING_ISSUE_TAGS_TABLE = "error_tracking_issue_tags"
ERROR_TRACKING_ISSUE_TAGS_RAW_TABLE = f"raw_{ERROR_TRACKING_ISSUE_TAGS_TABLE}"
ERROR_TRACKING_ISSUE_TAGS_WRITABLE_TABLE = f"writable_{ERROR_TRACKING_ISSUE_TAGS_TABLE}"
ERROR_TRACKING_ISSUE_TAGS_KAFKA_TABLE = f"kafka_{ERROR_TRACKING_ISSUE_TAGS_TABLE}"
ERROR_TRACKING_ISSUE_TAGS_MV = f"{ERROR_TRACKING_ISSUE_TAGS_TABLE}_mv"

ERROR_TRACKING_ISSUE_TAGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    issue_id UUID,
    key VARCHAR,
    value Nullable(Int8),
    is_deleted Int8,
    version Int64
    {extra_fields}
) ENGINE = {engine}
"""


def RAW_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL() -> str:
    return (
        ERROR_TRACKING_ISSUE_TAGS_TABLE_BASE_SQL
        + """
    ORDER BY (team_id, key, issue_id)
    SETTINGS index_granularity = 512
    """
    ).format(
        table_name=ERROR_TRACKING_ISSUE_TAGS_RAW_TABLE,
        engine=ReplacingMergeTree(ERROR_TRACKING_ISSUE_TAGS_RAW_TABLE, ver="version"),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(ERROR_TRACKING_ISSUE_TAGS_RAW_TABLE)}
    """,
    )


def _distributed_error_tracking_issue_tags_table_sql(table_name: str) -> str:
    return ERROR_TRACKING_ISSUE_TAGS_TABLE_BASE_SQL.format(
        table_name=table_name,
        engine=Distributed(data_table=ERROR_TRACKING_ISSUE_TAGS_RAW_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )


def WRITABLE_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL() -> str:
    return _distributed_error_tracking_issue_tags_table_sql(ERROR_TRACKING_ISSUE_TAGS_WRITABLE_TABLE)


def ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL() -> str:
    return _distributed_error_tracking_issue_tags_table_sql(ERROR_TRACKING_ISSUE_TAGS_TABLE)


def KAFKA_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL() -> str:
    return (
        ERROR_TRACKING_ISSUE_TAGS_TABLE_BASE_SQL
        + f"""
SETTINGS kafka_skip_broken_messages = 100,
         kafka_num_consumers = {kafka_num_consumers(1)},
         kafka_thread_per_consumer = 1,
         kafka_poll_timeout_ms = 10000,
         kafka_flush_interval_ms = 7500,
         kafka_max_block_size = 100000
"""
    ).format(
        table_name=ERROR_TRACKING_ISSUE_TAGS_KAFKA_TABLE,
        engine=kafka_engine(
            KAFKA_ERROR_TRACKING_ISSUE_TAGS,
            group=CONSUMER_GROUP_ERROR_TRACKING_ISSUE_TAGS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_SHARED_NAMED_COLLECTION,
        ),
        extra_fields="",
    )


def ERROR_TRACKING_ISSUE_TAGS_MV_SQL() -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {ERROR_TRACKING_ISSUE_TAGS_MV}
TO {ERROR_TRACKING_ISSUE_TAGS_WRITABLE_TABLE}
AS SELECT
team_id,
issue_id,
key,
value,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {settings.CLICKHOUSE_DATABASE}.{ERROR_TRACKING_ISSUE_TAGS_KAFKA_TABLE}
"""


def TRUNCATE_ERROR_TRACKING_ISSUE_TAGS_TABLE_SQL() -> str:
    return f"TRUNCATE TABLE IF EXISTS {ERROR_TRACKING_ISSUE_TAGS_RAW_TABLE}"


INSERT_ERROR_TRACKING_ISSUE_TAG = f"""
INSERT INTO {ERROR_TRACKING_ISSUE_TAGS_TABLE} (team_id, issue_id, key, value, is_deleted, version, _timestamp, _offset, _partition) SELECT %(team_id)s, %(issue_id)s, %(key)s, %(value)s, %(is_deleted)s, %(version)s, now(), 0, 0
"""


# IMPORTANT: The following table definitions are obsolete and were replaced by the general-purpose
# document_embeddings tables in migration 0155. However, they MUST remain here for historical
# migration compatibility - migration 0153 references these functions to create the tables,
# and migration 0155 drops them. Removing these definitions would break the migration chain.
# DO NOT remove these definitions or the functions below.

ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE = "error_tracking_issue_fingerprint_embeddings"
ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE = f"writable_{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}"
KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE = f"kafka_{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}"
ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV = f"{ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE}_mv"

ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    model_name LowCardinality(String),
    embedding_version Int64, -- This is the given iteration of the embedding approach - it will /probably/ always be 0, but we want to be able to iterate on e.g. what we feed the model, so we'll leave that door open for now
    fingerprint VARCHAR,
    inserted_at DateTime64(3, 'UTC'),
    embeddings Array(Float64) -- We could experiment with quantization, but if we do we can use a new column, for now we'll eat the inefficiency
    {extra_fields} -- Unused, I think, but the above has it, so
) ENGINE = {engine}
"""


def ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_ENGINE():
    return ReplacingMergeTree(ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE, ver="inserted_at")


def ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL():
    return (
        ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_BASE_SQL
        + """
    ORDER BY (team_id, model_name, embedding_version, fingerprint)
    SETTINGS index_granularity = 512
    """
    ).format(
        table_name=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE,
        engine=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE)}
    """,
    )


def ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE_SQL():
    return ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE,
        engine=Distributed(
            data_table=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE,
            cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )


def KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_SQL():
    return ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name=KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE,
        engine=kafka_engine(
            KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS, group="clickhouse_error_tracking_fingerprint_embeddings"
        ),
        extra_fields="",
    )


def ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV_SQL(
    target_table=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_WRITABLE_TABLE,
):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
team_id,
model_name,
embedding_version,
fingerprint,
_timestamp as inserted_at,
embeddings,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
""".format(
        mv_name=ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_MV,
        target_table=target_table,
        kafka_table=KAFKA_ERROR_TRACKING_FINGERPRINT_EMBEDDINGS_TABLE,
        database=settings.CLICKHOUSE_DATABASE,
    )
