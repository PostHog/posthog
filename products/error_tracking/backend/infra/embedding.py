"""Public re-export of embedding / indexed-embedding metadata.

This module is the sanctioned cross-product path for Error tracking
embedding DDL, MV names, Kafka topic constants, and ``EMBEDDING_TABLES``
metadata. Content lives in ``products.error_tracking.backend.embedding``
and ``products.error_tracking.backend.indexed_embedding``; frozen
ClickHouse migrations continue to import from those legacy paths via
tach shims. New code should import from
``products.error_tracking.backend.infra.embedding``.
"""

from products.error_tracking.backend.embedding import (
    DISTRIBUTED_DOCUMENT_EMBEDDINGS_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_MV_SQL,
    DOCUMENT_EMBEDDINGS_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL,
    PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS,
    TRUNCATE_DOCUMENT_EMBEDDINGS_TABLE_SQL,
)
from products.error_tracking.backend.indexed_embedding import (
    DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE_SQL,
    DOCUMENT_EMBEDDINGS_BUFFER_WRITABLE_TABLE_SQL,
    EMBEDDING_TABLES,
    KAFKA_TO_BUFFER_MV_SQL,
)

__all__ = [
    "DISTRIBUTED_DOCUMENT_EMBEDDINGS_TABLE_SQL",
    "DOCUMENT_EMBEDDINGS_BUFFER_SHARDED_TABLE_SQL",
    "DOCUMENT_EMBEDDINGS_BUFFER_WRITABLE_TABLE_SQL",
    "DOCUMENT_EMBEDDINGS_MV_SQL",
    "DOCUMENT_EMBEDDINGS_TABLE_SQL",
    "DOCUMENT_EMBEDDINGS_WRITABLE_TABLE_SQL",
    "EMBEDDING_TABLES",
    "KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL",
    "KAFKA_TO_BUFFER_MV_SQL",
    "PARTITIONED_SHARDED_DOCUMENT_EMBEDDINGS",
    "TRUNCATE_DOCUMENT_EMBEDDINGS_TABLE_SQL",
]
