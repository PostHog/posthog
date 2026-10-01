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
