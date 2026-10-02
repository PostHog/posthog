from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_DOCUMENT_EMBEDDINGS, kafka_engine
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_TOPIC

DOCUMENT_EMBEDDINGS = "posthog_document_embeddings"
PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS = f"partitioned_sharded_{DOCUMENT_EMBEDDINGS}"


# The flow of this table set, as per other sharded tables, is:
# - Kafka table exposes messages from Kafka topic
# - Materialized view reads from Kafka table, writes to writable table, moving the kafka offset
# - Writable table distributes writes to sharded tables
# - Distributed table distributes reads to sharded tables


# WarpStream-shared Kafka engine table + MV (coexist alongside MSK tables, same target writable
# table). The MSK side stays in place during the cut-over and gets dropped in a follow-up
# migration once produce traffic has shifted to the shared cluster.

KAFKA_DOCUMENT_EMBEDDINGS = f"kafka_{DOCUMENT_EMBEDDINGS}"

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
    content String{content_default}, -- The actual text content that was embedded
    metadata String{metadata_default}, -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    {extra_fields}
) ENGINE = {engine}
"""


def KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL():
    return DOCUMENT_EMBEDDINGS_TABLE_BASE_SQL.format(
        table_name=KAFKA_DOCUMENT_EMBEDDINGS,
        engine=kafka_engine(KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, group=CONSUMER_GROUP_DOCUMENT_EMBEDDINGS),
        content_default="",
        metadata_default="",
        extra_fields="",
    )
