from django.conf import settings

from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_TOPIC

#

DOCUMENT_EMBEDDINGS = "posthog_document_embeddings"
DOCUMENT_EMBEDDING_WRITABLE = f"writable_{DOCUMENT_EMBEDDINGS}"
KAFKA_DOCUMENT_EMBEDDINGS = f"kafka_{DOCUMENT_EMBEDDINGS}"
DOCUMENT_EMBEDDINGS_MV = f"{DOCUMENT_EMBEDDINGS}_mv"

DOCUMENT_EMBEDDINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket, you'd use this to ask clickhouse "what kind of documents do I have embeddings for, related to session replay"
    document_type LowCardinality(String), -- The type of document this is an embedding for, e.g. "issue_fingerprint", "session_summary", "task_update" etc.
    model_name LowCardinality(String), -- The name of the model used to generate this embedding. Includes embedding dimensionality, appended as e.g. "text-embedding-3-small-1024"
    rendering LowCardinality(String), -- How the document was rendered to text, e.g. "with_error_message", "as_html" etc. Use "plain" if it was already text.
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time (or similar), rather than the time the embedding was created
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted (if a duplicate-key row was inserted, for example, this is what we use to choose the winner)
    embedding Array(Float64) -- The embedding itself
    {extra_fields}
) ENGINE = {engine}
"""


def DOCUMENT_EMBEDDINGS_TABLE_ENGINE():
    return ReplacingMergeTree(DOCUMENT_EMBEDDINGS, ver="inserted_at")


def DOCUMENT_EMBEDDINGS_TABLE_SQL():
    return (
        DOCUMENT_EMBEDDINGS_TABLE_BASE_SQL
        + """
    -- This index assumes:
    --  - people will /always/ provide a date range
    --  - "show me documents of type X by any model" will be more common than "show me all documents by model X"
    --  - Documents with the same ID whose timestamp is in the same day are the same document, and the later inserted one should be retained
    ORDER BY (team_id, toDate(timestamp), product, document_type, model_name, rendering, cityHash64(document_id))
    SETTINGS index_granularity = 512
    """
    ).format(
        table_name=DOCUMENT_EMBEDDINGS,
        engine=DOCUMENT_EMBEDDINGS_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(DOCUMENT_EMBEDDINGS)}
    """,
    )


def DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL():
    return DOCUMENT_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name=DOCUMENT_EMBEDDING_WRITABLE,
        engine=Distributed(
            data_table=DOCUMENT_EMBEDDINGS,
            cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
    )


def KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL():
    return DOCUMENT_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name=KAFKA_DOCUMENT_EMBEDDINGS,
        engine=kafka_engine(KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, group="clickhouse_document_embeddings"),
        extra_fields="",
    )


def DOCUMENT_EMBEDDINGS_MV_SQL(
    target_table=DOCUMENT_EMBEDDING_WRITABLE,
):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
team_id,
product,
document_type,
model_name,
rendering,
document_id,
timestamp,
_timestamp as inserted_at,
embedding,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
""".format(
        mv_name=DOCUMENT_EMBEDDINGS_MV,
        target_table=target_table,
        kafka_table=KAFKA_DOCUMENT_EMBEDDINGS,
        database=settings.CLICKHOUSE_DATABASE,
    )


def TRUNCATE_DOCUMENT_EMBEDDINGS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {DOCUMENT_EMBEDDINGS} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
