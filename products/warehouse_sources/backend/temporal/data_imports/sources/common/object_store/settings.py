# A bucket listing is one flat, paginated walk (1,000 keys per request), so these caps bound both the
# request count and the memory a listing holds.
MAX_DISCOVERY_OBJECTS = 10_000
# A sync lists only the table's own folder. The cap is higher than discovery's because a sync that
# silently skipped files would replace the table with a partial copy, so going past it fails the sync.
MAX_TABLE_OBJECTS = 50_000
# A listing also walks folder marker keys (ending in `/`), which are never files, so the walk has its own cap.
MAX_LISTED_KEYS = 100_000
# One table per root-level file can turn a large flat folder into thousands of tables.
MAX_TABLES = 1_000

# How old a file's modification time must be before an append-only sync reads it. Object stores
# stamp files to the second, so a younger timestamp can still be given to another file.
APPEND_SETTLE_SECONDS = 60

CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 60
MAX_REQUEST_ATTEMPTS = 3

CSV_BLOCK_SIZE_BYTES = 4 * 1024 * 1024
JSONL_CHUNK_ROWS = 5_000
JSONL_CHUNK_BYTES = 64 * 1024 * 1024
# One JSON Lines record, or the first line of a CSV file, is held whole in memory to be parsed. A gzip
# file can expand far past its stored size, so reads stop at this many decompressed bytes.
MAX_RECORD_BYTES = 32 * 1024 * 1024
# The first record of a CSV file names the columns, and is read whole before the streaming reader starts.
MAX_FIRST_CSV_RECORD_BYTES = 1024 * 1024
# A gzipped Parquet file is unpacked to local disk to be read, so the unpacked size is capped too.
MAX_UNPACKED_PARQUET_BYTES = 2 * 1024 * 1024 * 1024
PARQUET_BATCH_ROWS = 10_000
DELTA_BATCH_ROWS = 16_384

# Arrow batches from wide files can be large, so the pipeline's batcher flushes before this many bytes.
CHUNK_SIZE_BYTES = 100 * 1024 * 1024
