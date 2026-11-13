"""Shared constants for the intent topics pipeline."""

from products.error_tracking.backend.indexed_embedding import SMALL_256_MODEL_NAME

EMBEDDING_MODEL = SMALL_256_MODEL_NAME
EMBEDDING_DIMENSION = 256
EMBEDDING_PRODUCT = "mcp_analytics"
EMBEDDING_DOCUMENT_TYPE = "mcp-intent"
EMBEDDING_RENDERING = "raw"
# The 256-dimension model table keeps rows for one month; an intent older than this has no vector.
EMBEDDING_RETENTION_DAYS = 30

# Intent text sent for embedding, in characters. Above the model's input limit anyway, and it keeps an
# escaped request far below the Kafka message limit; the hash still covers the full text.
MAX_EMBEDDING_TEXT_LENGTH = 8_000
# Hourly sync: once a run has read this many distinct intents it stops at the next hour boundary, and the
# next run resumes there. An hour is always read whole, so the budget bounds a catch-up without dropping intents.
MAX_INTENTS_PER_SYNC = 200_000
# Seen-hash lookups go to ClickHouse in chunks this size. The vector table is sorted by cityHash64(document_id)
# within each day, and an hour's hashes spread over every granule, so each chunk reads the team's whole retention
# window: one chunk per page of distinct intents keeps it to one read per page. 50k hashes are ~3.4 MB of SQL,
# well under the client's max_query_size.
HASH_CHUNK_SIZE = 50_000
# Text kept on the assignment row for the map and outlier lists.
MAX_ASSIGNMENT_TEXT_LENGTH = 500
# Weekly fit: distinct intents sampled from the last week.
FIT_SAMPLE_SIZE = 20_000
FIT_LOOKBACK_DAYS = 7
MIN_INTENTS_FOR_FIT = 50
# Topics no cluster has matched for this long are archived.
TOPIC_ARCHIVE_AFTER_DAYS = 30
