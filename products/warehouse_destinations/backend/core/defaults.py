"""Default tuning values for destinations.

A caller that tunes these values per environment passes its own value to the constructor.
"""

TRANSFORMER_MAX_WORKERS = 2
PARQUET_MAX_BUFFERED_ARROW_BYTES = 32 * 1024 * 1024
POSTGRES_UPLOAD_CHUNK_SIZE_BYTES = 50 * 1024 * 1024
