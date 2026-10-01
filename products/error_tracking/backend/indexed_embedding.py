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

# Define the models currently in use
EMBEDDING_MODELS_1 = [
    "text-embedding-3-small-1536",
    "text-embedding-3-large-3072",
]

# If you want to add a new model or dimensionality you need to:
# - Add the new models to a new list like the one above
# - Create a new list like EMBEDDING_TABLES_1
# - Add that new list to EMBEDDING_TABLES full-list, so all the HOGQL modelling is automatically updated
# - Declare the tables and the materialized view of each new model in
#   posthog/clickhouse/schema/modules/document_embeddings


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


# Create table definition objects for each model
EMBEDDING_TABLES_1 = [ModelTableDefinitions(model_name) for model_name in EMBEDDING_MODELS_1]

# Unified list of all embedding tables (using spread pattern for future additions)
EMBEDDING_TABLES = [
    *EMBEDDING_TABLES_1,
    # Future: *EMBEDDING_TABLES_2, etc.
]
