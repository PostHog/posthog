DEFAULT_CHUNK_SIZE = 20_000
DEFAULT_TABLE_SIZE_BYTES = 150 * 1024 * 1024  # 150 MB
# Ceiling on the estimated per-chunk row count, expressed as total cells (rows × columns).
# The byte-based chunk-size estimate divides a memory budget by the Postgres *text wire size*
# of a row, which badly underestimates the in-memory footprint of a wide row: every row is
# materialized as a Python dict holding one object per column, then converted to a PyArrow
# table (and merged into Delta) — so peak memory scales with rows × columns, not with text
# length. For a wide table (tens of columns) the wire estimate produces six-figure row chunks
# that OOM the worker. Bounding total cells per chunk keeps that working set in check while
# leaving narrow tables (where the byte estimate already lands well under this ceiling)
# untouched.
MAX_CHUNK_CELLS = 5_000_000
PARTITION_KEY = "_ph_partition_key"
