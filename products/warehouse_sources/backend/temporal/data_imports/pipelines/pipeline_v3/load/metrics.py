from prometheus_client import Counter, Gauge, Histogram

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

# Deliberately unlabelled by team: this fires on every sync of every over-fragmented table fleet-wide,
# which is the whole population the coarsening rollout is aimed at, so a team label would explode
# cardinality. `reason` is a bounded set of gate names, which is what "why isn't coarsening firing"
# actually needs; per-table detail stays in the operator-facing INFO log on a nominated table.
DELTA_COARSEN_DECLINE_TOTAL = Counter(
    "warehouse_load_delta_coarsen_decline_total",
    "Over-fragmented tables the controller declined to coarsen, by gate",
    labelnames=["reason"],
)

CDC_SEQ_GUARD_ROWS_DROPPED_TOTAL = Counter(
    "warehouse_load_cdc_seq_guard_rows_dropped_total",
    "CDC rows dropped before the write as already-applied, by reason",
    labelnames=["team_id", "reason"],
)

# Non-zero means a DELETE is about to erase data the target still holds. Alert on this; enrichment
# failing has no other detector.
CDC_DELETE_ENRICHMENT_VIOLATIONS_TOTAL = Counter(
    "warehouse_load_cdc_delete_enrichment_violations_total",
    "DELETE rows that would null a data column the target currently holds",
    labelnames=["team_id"],
)

# deltalite real-write path (phase 2). `outcome` is one of:
#   written    - deltalite performed the incremental merge and committed
#   fallback   - deltalite was enabled but failed (or refused), so the delta-rs MERGE ran instead
DELTALITE_WRITE_TOTAL = Counter(
    "warehouse_load_deltalite_write_total",
    "Incremental merges routed to deltalite's real write path, by outcome",
    labelnames=["outcome"],
)

DELTALITE_WRITE_DURATION_SECONDS = Histogram(
    "warehouse_load_deltalite_write_duration_seconds",
    "Wall-clock time of a deltalite real write (DeltaLiteTable.upsert)",
)

# deltalite memory governor (capacity planning). Sizes each upsert's knobs to a fixed per-upsert
# slice of pod memory ((limit * safety - reserve) / max_concurrent), so all concurrent upserts fit
# and deltalite never falls back to the MERGE for capacity. deltalite always writes.
#   mode    - off | advisory | enforce
#   outcome - admitted | capacity_exceeded (source too big for its slice; ran at mpp=1)
DELTALITE_GOVERNOR_DECISION_TOTAL = Counter(
    "warehouse_load_deltalite_governor_decision_total",
    "deltalite governor sizing decisions, by mode and outcome",
    labelnames=["mode", "outcome"],
)

DELTALITE_GOVERNOR_PREDICTED_PEAK_MB = Histogram(
    "warehouse_load_deltalite_governor_predicted_peak_mb",
    "Predicted marginal peak RSS (MB) the governor sized an upsert against",
    buckets=(128, 256, 512, 1024, 2048, 4096, 8192, 16384),
)

DELTALITE_GOVERNOR_INFLIGHT = Gauge(
    "warehouse_load_deltalite_governor_inflight",
    "deltalite upserts currently admitted and in flight on this process",
)

DELTALITE_GOVERNOR_RESERVED_MB = Gauge(
    "warehouse_load_deltalite_governor_reserved_mb",
    "Total memory (MB) currently reserved by in-flight deltalite upserts on this process",
)
