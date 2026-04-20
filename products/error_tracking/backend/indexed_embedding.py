"""
Model-specific embedding tables with vector indexes.

Outline of pipeline here is (I've elided sharded/distributed/writable details here):
```
Embedding Topic
  → Kafka Table
    → Buffer MV (single on-off tap)
      → Buffer Table (1 dat TTL)
        → Model-Specific MVs (filter from buffer)
          → Model Specific Tables (indexed, 3 month TTL, partitioned weekly)
            → model specific document_embeddings tables (in hogql)
              → General document_embeddings table (in hogql) (adds model_name back, dynamically routes queries)
```
The general structure is to have a table _per embedding model/dimensionality pair_, to allow us to use data skipping vector similarity indexes (which require the vectors in the underlying column to be all the same size). These tables also have a TTL, to keep the size of those indexes bounded, and then there's an extra buffering step so there's one place to atomically halt ingestion during table maintenance. The reason the size of those indexes needs to be bounded is because the _entire index_ needs to be held in memory when used.

Then we expose a lazy table in hogql, which routes the query to the right model-specific table dynamically, on the basis of which model is being used in the `WHERE` clause of the query. This lazy table also adds a `FINAL` to the `JoinExpr`, because the `argMax` subquery approach to selecting the final version of a dataset breaks vector index usage (at least for now - I'm 99% sure the problem is the `GROUP BY` that approach necessitates, as even the example below contains a subquery, just without grouping).

All of this means hogql queries like:
```sql
WITH embedText('Bug in session replay page', 'text-embedding-3-large-3072') as query,
SELECT product, document_type, rendering, content, cosineDistance(embedding, query) as dist FROM document_embeddings WHERE model_name = 'text-embedding-3-large-3072' ORDER BY dist
```

Become clickhouse sql that looks like:
```sql
SELECT
    document_embeddings.product AS product,
    document_embeddings.document_type AS document_type,
    document_embeddings.rendering AS rendering,
    document_embeddings.content AS content,
    cosineDistance(document_embeddings.embedding, [omitted]) AS dist
FROM
    (SELECT
        distributed_posthog_document_embeddings_text_embedding_3_large_3072.product AS product,
        distributed_posthog_document_embeddings_text_embedding_3_large_3072.document_type AS document_type,
        distributed_posthog_document_embeddings_text_embedding_3_large_3072.rendering AS rendering,
        distributed_posthog_document_embeddings_text_embedding_3_large_3072.content AS content,
        distributed_posthog_document_embeddings_text_embedding_3_large_3072.embedding AS embedding,
        'text-embedding-3-large-3072' AS model_name,
        distributed_posthog_document_embeddings_text_embedding_3_large_3072.document_id AS document_id
    FROM
        distributed_posthog_document_embeddings_text_embedding_3_large_3072 FINAL
    WHERE
        equals(distributed_posthog_document_embeddings_text_embedding_3_large_3072.team_id, 1)) AS document_embeddings
WHERE
    ifNull(equals(document_embeddings.model_name, 'text-embedding-3-large-3072'), 0)
ORDER BY
    dist ASC
LIMIT 101
OFFSET 0
```

With query plans like:
```
Expression (Project names)
  Limit (preliminary LIMIT (without OFFSET))
    Sorting (Sorting for ORDER BY)
      Expression ((Before ORDER BY + Projection))
        Filter (((WHERE + (Change column names to column identifiers + (Change remote column names to local column names + ( + (Project names + Projection))))) + (WHERE + Change column names to column identifiers)))
          ReadFromMergeTree (default.sharded_posthog_document_embeddings_text_embedding_3_large_3072)
          Indexes:
            MinMax
              Condition: true
              Parts: 3/3
              Granules: 3/3
            Partition
              Condition: true
              Parts: 3/3
              Granules: 3/3
            PrimaryKey
              Keys:
                team_id
              Condition: (team_id in [1, 1])
              Parts: 3/3
              Granules: 3/3
              Search Algorithm: binary search
            Skip
              Name: embedding_idx_cosine
              Description: vector_similarity GRANULARITY 100000000
              Parts: 3/3
              Granules: 3/3
            PrimaryKeyExpand
              Description: Selects all granules that intersect by PK values with the previous skip indexes selection
              Parts: 3/3
              Granules: 3/3
              Ranges: 3
```

The really important bit there being that `Skip` index usage - all of this architecture is built to allow us to use them.
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

# Name of the Kafka-to-buffer MV
KAFKA_TO_BUFFER_MV = "posthog_document_embeddings_kafka_to_buffer_mv"


# Base SQL template for buffer tables
def _buffer_table_sql(table_name: str, engine) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    product LowCardinality(String),
    document_type LowCardinality(String),
    model_name LowCardinality(String),  -- Used for filtering in model-specific MVs
    rendering LowCardinality(String),
    document_id String,
    timestamp DateTime64(3, 'UTC'),
    inserted_at DateTime64(3, 'UTC'),
    content String DEFAULT '',
    metadata String DEFAULT '{{}}',
    embedding Array(Float64)
    {KAFKA_COLUMNS_WITH_PARTITION}
) ENGINE = {engine}"""


# SQL for sharded buffer table on data nodes that receives all embeddings from Kafka
def DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE_SQL():
    from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme

    engine = ReplacingMergeTree(
        DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE, ver="inserted_at", replication_scheme=ReplicationScheme.SHARDED
    )

    return (
        _buffer_table_sql(DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE, engine)
        + """
PARTITION BY toDate(inserted_at)
ORDER BY (inserted_at, model_name, cityHash64(document_id))
TTL inserted_at + INTERVAL 1 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""
    )


# SQL for writable distributed buffer table on ingestion nodes (writes to sharded buffer on data nodes)
def DOCUMENT_EMBEDDINGS_BUFFER_WRITABLE_TABLE_SQL():
    from posthog.clickhouse.table_engines import Distributed

    engine = Distributed(
        data_table=DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE,
        sharding_key="cityHash64(document_id)",
    )

    return _buffer_table_sql(DOCUMENT_EMBEDDINGS_BUFFER_WRITABLE_TABLE, engine) + "\n"


# Buffer tables: Data flows from Kafka -> writable buffer (ingestion) -> sharded buffer (data nodes)
DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE = (
    "sharded_posthog_document_embeddings_buffer"  # Persistent storage on data nodes
)
DOCUMENT_EMBEDDINGS_BUFFER_WRITABLE_TABLE = (
    "writable_posthog_document_embeddings_buffer"  # Stateless proxy on ingestion nodes
)

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
        target_table=DOCUMENT_EMBEDDINGS_BUFFER_WRITABLE_TABLE,
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
            buffer_table=DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE,
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
AS {" UNION ALL ".join(union_parts)}"""

    return view_sql
