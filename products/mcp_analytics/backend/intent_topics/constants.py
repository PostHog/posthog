"""Shared constants for the intent topics pipeline."""

from products.error_tracking.backend.indexed_embedding import SMALL_256_MODEL_NAME

EMBEDDING_MODEL = SMALL_256_MODEL_NAME
EMBEDDING_DIMENSION = 256
EMBEDDING_PRODUCT = "mcp_analytics"
EMBEDDING_DOCUMENT_TYPE = "mcp-intent"
EMBEDDING_RENDERING = "raw"
# The 256-dimension model table keeps rows for one month; an intent older than this has no vector.
EMBEDDING_RETENTION_DAYS = 30

# Hourly sync: once a run has read this many distinct intents it stops at the next hour boundary, and the
# next run resumes there. An hour is always read whole, so the budget bounds a catch-up without dropping intents.
MAX_INTENTS_PER_SYNC = 200_000
# Seen-hash lookups and inserts go to ClickHouse in chunks this size.
HASH_CHUNK_SIZE = 10_000
# Text kept on the assignment row for the map and outlier lists.
MAX_ASSIGNMENT_TEXT_LENGTH = 500
# Weekly fit: distinct intents sampled from the last week.
FIT_SAMPLE_SIZE = 20_000
FIT_LOOKBACK_DAYS = 7
MIN_INTENTS_FOR_FIT = 50
# Topics no cluster has matched for this long are archived.
TOPIC_ARCHIVE_AFTER_DAYS = 30
