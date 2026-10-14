# A bucket listing is one flat, paginated walk (1,000 keys per request), so these caps bound both the
# request count and the memory a listing holds.
MAX_DISCOVERY_OBJECTS = 10_000
# A sync lists only the table's own folder. The cap is higher than discovery's because a sync that
# silently skipped files would replace the table with a partial copy, so going past it fails the sync.
MAX_TABLE_OBJECTS = 50_000
# One table per root-level file can turn a large flat folder into thousands of tables.
MAX_TABLES = 1_000

CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 60
MAX_REQUEST_ATTEMPTS = 3

CSV_BLOCK_SIZE_BYTES = 4 * 1024 * 1024
JSONL_CHUNK_ROWS = 5_000
JSONL_CHUNK_BYTES = 64 * 1024 * 1024
# One JSON Lines record, or the first line of a CSV file, is held whole in memory to be parsed. A gzip
# file can expand far past its stored size, so reads stop at this many decompressed bytes.
MAX_RECORD_BYTES = 32 * 1024 * 1024
PARQUET_BATCH_ROWS = 10_000
DELTA_BATCH_ROWS = 16_384

# Arrow batches from wide files can be large, so the pipeline's batcher flushes before this many bytes.
CHUNK_SIZE_BYTES = 100 * 1024 * 1024
