"""
Model-specific embedding tables with vector indexes.

Each embedding model (e.g., 'text-embedding-1024') gets its own set of tables
optimized for that specific vector dimension, with proper vector similarity indexes.
"""

from typing import Optional

from django.conf import settings

from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

# Base SQL template for model-specific tables - same as original but without model_name column
MODEL_SPECIFIC_EMBEDDINGS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket
    document_type LowCardinality(String), -- The type of document this is an embedding for
    rendering LowCardinality(String), -- How the document was rendered to text
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted
    content String{content_default}, -- The actual text content that was embedded
    metadata String{metadata_default}, -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    {extra_fields}
) ENGINE = {engine}
"""

# SQL template for sharded table with partitioning and TTL
MODEL_SPECIFIC_SHARDED_TABLE_SQL = (
    MODEL_SPECIFIC_EMBEDDINGS_TABLE_BASE_SQL
    + """
    PARTITION BY toMonday(timestamp)
    ORDER BY (team_id, toDate(timestamp), product, document_type, rendering, cityHash64(document_id))
    TTL timestamp + INTERVAL 3 MONTH
    SETTINGS index_granularity = 512, ttl_only_drop_parts = 1
    """
)

# SQL template for materialized view that reads from buffer table and filters by model_name
MODEL_SPECIFIC_MV_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {target_table}
AS SELECT
team_id,
product,
document_type,
rendering,
document_id,
timestamp,
inserted_at,
content,
metadata,
embedding,
_timestamp,
_offset,
_partition
FROM {database}.{buffer_table}
WHERE model_name = '{model_name}'
"""


# SQL for buffer table that receives all embeddings from Kafka
def DOCUMENT_EMBEDDINGS_BUFFER_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    product LowCardinality(String),
    document_type LowCardinality(String),
    model_name LowCardinality(String),  -- Keep this for filtering in model-specific MVs
    rendering LowCardinality(String),
    document_id String,
    timestamp DateTime64(3, 'UTC'),
    inserted_at DateTime64(3, 'UTC'),
    content String DEFAULT '',
    metadata String DEFAULT '{{}}',
    embedding Array(Float64){extra_fields}
) ENGINE = MergeTree()
PARTITION BY toDate(inserted_at)
ORDER BY (inserted_at, model_name, cityHash64(document_id))
TTL inserted_at + INTERVAL 1 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
""".format(table_name=DOCUMENT_EMBEDDINGS_BUFFER_TABLE, extra_fields=KAFKA_COLUMNS_WITH_PARTITION)


# Name of the buffer table
DOCUMENT_EMBEDDINGS_BUFFER_TABLE = "posthog_document_embeddings_buffer"

# Name of the Kafka-to-buffer MV
KAFKA_TO_BUFFER_MV = "posthog_document_embeddings_kafka_to_buffer_mv"

# Define the models currently in use
EMBEDDING_MODELS_1 = [
    "text-embedding-3-small-1536",
    "text-embedding-3-large-3072",
]

# If you want to add a new model or dimensionality you need to:
# - Add the new models to a new list like the one above
# - Create a new list like EMBEDDING_TABLES_1
# - Add that new list to EMBEDDING_TABLES full-list, so all the HOGQL modelling is automatically updated
# And then write a migration (similar to 0187_model_specific_embedding_tables) that:
# - Drop the buffer-table-filling MV
# - Create the new tables and MVs for the new model-specific tables
# - Re-creates the buffer-table-filling MV


# Helper functions for pausing/resuming the entire embedding system
def drop_kafka_to_buffer_mv_sql() -> str:
    """Drop the Kafka-to-buffer MV to pause all embedding consumption."""
    return f"DROP TABLE IF EXISTS {KAFKA_TO_BUFFER_MV} "


def KAFKA_TO_BUFFER_MV_SQL() -> str:
    """Create the Kafka-to-buffer MV to resume embedding consumption."""
    from products.error_tracking.backend.embedding import KAFKA_DOCUMENT_EMBEDDINGS

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
coalesce(content, '') as content,
coalesce(metadata, '{{}}') as metadata,
embedding,
_timestamp,
_offset,
_partition
FROM {database}.{kafka_table}
""".format(
        mv_name=KAFKA_TO_BUFFER_MV,
        target_table=DOCUMENT_EMBEDDINGS_BUFFER_TABLE,
        kafka_table=KAFKA_DOCUMENT_EMBEDDINGS,
        database=settings.CLICKHOUSE_DATABASE,
    )


class ModelTableDefinitions:
    def __init__(self, model_name: str, dimension: Optional[int] = None):
        self.model_name = model_name

        # Parse dimension from model name if not provided
        if dimension is None:
            parts = model_name.split("-")
            if parts and parts[-1].isdigit():
                self.dimension = int(parts[-1])
            else:
                raise ValueError(f"Could not parse dimension from model_name '{model_name}' and no dimension provided")
        else:
            self.dimension = dimension

        # Normalize model name for use in table names (replace hyphens with underscores)
        self.normalized_model_name = model_name.replace("-", "_")

    # Table names

    def sharded_table_name(self) -> str:
        return f"sharded_posthog_document_embeddings_{self.normalized_model_name}"

    def distributed_table_name(self) -> str:
        return f"distributed_posthog_document_embeddings_{self.normalized_model_name}"

    def writable_table_name(self) -> str:
        return f"writable_posthog_document_embeddings_{self.normalized_model_name}"

    def materialized_view_name(self) -> str:
        return f"posthog_document_embeddings_{self.normalized_model_name}_mv"

    # SQL statements for creating tables

    def sharded_table_sql(self) -> str:
        dim_constraint_sql = f"CONSTRAINT embedding_dimension_check CHECK length(embedding) = {self.dimension}"
        return MODEL_SPECIFIC_SHARDED_TABLE_SQL.format(
            table_name=self.sharded_table_name(),
            dimension=self.dimension,
            engine=ReplacingMergeTree(
                self.sharded_table_name(), ver="inserted_at", replication_scheme=ReplicationScheme.SHARDED
            ),
            content_default=" DEFAULT ''",
            metadata_default=" DEFAULT '{}'",
            extra_fields=f"""{KAFKA_COLUMNS_WITH_PARTITION}, {index_by_kafka_timestamp(self.sharded_table_name())}, {dim_constraint_sql}""",
        )

    def distributed_table_sql(self) -> str:
        return MODEL_SPECIFIC_EMBEDDINGS_TABLE_BASE_SQL.format(
            table_name=self.distributed_table_name(),
            engine=Distributed(
                data_table=self.sharded_table_name(),
                sharding_key="cityHash64(document_id)",
            ),
            content_default=" DEFAULT ''",
            metadata_default=" DEFAULT '{}'",
            extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
        )

    def writable_table_sql(self) -> str:
        return MODEL_SPECIFIC_EMBEDDINGS_TABLE_BASE_SQL.format(
            table_name=self.writable_table_name(),
            engine=Distributed(
                data_table=self.sharded_table_name(),
                sharding_key="cityHash64(document_id)",
            ),
            content_default=" DEFAULT ''",
            metadata_default=" DEFAULT '{}'",
            extra_fields=KAFKA_COLUMNS_WITH_PARTITION,
        )

    def materialized_view_sql(self) -> str:
        return MODEL_SPECIFIC_MV_SQL.format(
            mv_name=self.materialized_view_name(),
            target_table=self.writable_table_name(),
            buffer_table=DOCUMENT_EMBEDDINGS_BUFFER_TABLE,
            database=settings.CLICKHOUSE_DATABASE,
            model_name=self.model_name,
        )

    # SQL statements for dropping tables

    def drop_materialized_view_sql(self) -> str:
        return f"DROP TABLE IF EXISTS {self.materialized_view_name()}"

    def drop_distributed_sql(self) -> str:
        return f"DROP TABLE IF EXISTS {self.distributed_table_name()}"

    def drop_writable_sql(self) -> str:
        return f"DROP TABLE IF EXISTS {self.writable_table_name()}"

    def truncate_sharded_sql(self) -> str:
        return f"TRUNCATE TABLE IF EXISTS {self.sharded_table_name()}"

    def add_vector_index_sql(self) -> list[str]:
        """SQL to add vector similarity indexes to the sharded table after creation."""
        # Create two indexes - one for L2 distance and one for cosine distance
        # This allows callers to use either distance function efficiently
        return [
            f"ALTER TABLE {self.sharded_table_name()} ADD INDEX IF NOT EXISTS embedding_idx_l2 embedding TYPE vector_similarity('hnsw', 'L2Distance', {self.dimension})",
            f"ALTER TABLE {self.sharded_table_name()} ADD INDEX IF NOT EXISTS embedding_idx_cosine embedding TYPE vector_similarity('hnsw', 'cosineDistance', {self.dimension})",
        ]


# Create table definition objects for each model
EMBEDDING_TABLES_1 = [ModelTableDefinitions(model_name) for model_name in EMBEDDING_MODELS_1]

# Unified list of all embedding tables (using spread pattern for future additions)
EMBEDDING_TABLES = [
    *EMBEDDING_TABLES_1,
    # Future: *EMBEDDING_TABLES_2, etc.
]


# Union view that combines all model-specific tables and adds model_name column back
def DOCUMENT_EMBEDDINGS_UNION_VIEW_SQL() -> str:
    """
    Create a UNION ALL view combining all model-specific distributed tables.
    Adds model_name column back for backward compatibility with queries.
    """
    union_parts = []
    for model_table in EMBEDDING_TABLES:
        model_name = model_table.model_name
        distributed_table = model_table.distributed_table_name()

        # Each part selects all columns and adds model_name as a constant
        union_parts.append(f"""
        SELECT
            team_id,
            product,
            document_type,
            rendering,
            document_id,
            timestamp,
            inserted_at,
            content,
            metadata,
            embedding,
            _timestamp,
            _offset,
            _partition,
            '{model_name}' AS model_name
        FROM {distributed_table}""")

    view_sql = f"""CREATE VIEW IF NOT EXISTS posthog_document_embeddings_union_view
AS {' UNION ALL '.join(union_parts)}"""

    return view_sql
