DEFAULT_CHUNK_SIZE = 20_000
DEFAULT_TABLE_SIZE_BYTES = 150 * 1024 * 1024  # 150 MB
PARTITION_KEY = "_ph_partition_key"
# Per-run timestamp stamped on every row of a "full refresh - append" sync. All rows written by a
# single run share the same value (the job's created_at), so a distinct value identifies one snapshot.
# Retention prunes whole snapshots by deleting rows whose value falls outside the retention window.
SNAPSHOT_COLUMN = "_ph_snapshot_at"
