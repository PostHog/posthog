from prometheus_client import Counter, Histogram

DELTA_WRITE_DURATION_SECONDS = Histogram(
    "warehouse_load_delta_write_duration_seconds",
    "Duration of Delta Lake write operations",
    labelnames=["team_id", "schema_id", "write_type"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

DELTA_ROWS_WRITTEN_TOTAL = Counter(
    "warehouse_load_delta_rows_written_total",
    "Total rows written to Delta Lake",
    labelnames=["team_id", "schema_id"],
)

IDEMPOTENCY_HIT_TOTAL = Counter(
    "warehouse_load_idempotency_hit_total",
    "Total idempotency cache hits (batch already processed)",
    labelnames=["team_id", "schema_id"],
)

PARQUET_READ_DURATION_SECONDS = Histogram(
    "warehouse_load_parquet_read_duration_seconds",
    "Duration of S3 parquet file reads",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

POST_LOAD_DURATION_SECONDS = Histogram(
    "warehouse_load_post_load_duration_seconds",
    "Duration of post-load operations",
    labelnames=["operation"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

# TODO: the `team_id`/`schema_id` labels below are high cardinality — keep only for the gated rollout
# so we can debug per-team behaviour, then drop them before fully rolling out (per-team diagnosability
# is also covered by the `warehouse_repartition_*` capture events).
DELTA_REPARTITION_DURATION_SECONDS = Histogram(
    "warehouse_load_delta_repartition_duration_seconds",
    "Duration of an in-place Delta table repartition",
    labelnames=["team_id", "schema_id"],
    buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0),
)

DELTA_REPARTITION_TOTAL = Counter(
    "warehouse_load_delta_repartition_total",
    "Total in-place Delta repartitions by outcome",
    labelnames=["team_id", "outcome"],
)

DELTA_REPARTITION_SKIP_TOTAL = Counter(
    "warehouse_load_delta_repartition_skip_total",
    "Tables over the partition-size budget that the controller skipped, by reason",
    labelnames=["team_id", "reason"],
)
