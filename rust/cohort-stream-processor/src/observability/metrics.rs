//! Prometheus recorder setup and the service's metric vocabulary. The ~35 application
//! metrics (TDD §8.1) are registered by the pipeline modules as they are built; this
//! installs the global recorder, returns the render handle consumed by `GET /metrics`,
//! and owns the metric-name constants so every emitter uses the same series.

use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

// ── Filter catalog (PR 1.3) ───────────────────────────────────────────────────
/// Teams with ≥1 realtime cohort in the current catalog snapshot (gauge).
pub const FILTER_CATALOG_TEAMS: &str = "filter_catalog_teams";
/// Distinct `conditionHash`es across all teams in the current snapshot (gauge).
pub const FILTER_CATALOG_UNIQUE_CONDITIONS: &str = "filter_catalog_unique_conditions";
/// Leaves dropped during parse, labelled by `reason` (counter).
pub const FILTER_CATALOG_SKIPPED_LEAVES: &str = "filter_catalog_skipped_leaves_total";
/// Cohorts skipped because their filter tree failed to parse (counter).
pub const FILTER_CATALOG_COHORT_PARSE_ERRORS: &str = "filter_catalog_cohort_parse_errors_total";

// ── Store (PR 1.2) ─────────────────────────────────────────────────────────────
/// RocksDB batch commits (multi-CF `WriteBatch`, `delete_partition`, …), labelled by
/// `op` (counter).
pub const STORE_WRITE_BATCH_TOTAL: &str = "store_write_batch_total";
/// Latency of a committed RocksDB write, labelled by `op` (histogram, seconds).
pub const STORE_WRITE_DURATION_SECONDS: &str = "store_write_duration_seconds";
/// RocksDB operations that returned an error, labelled by `op` (counter).
pub const STORE_ERRORS_TOTAL: &str = "store_errors_total";
/// Malformed inputs the `cf_person_index` merge operator skipped instead of panicking
/// (a panic on a compaction thread is FFI UB), labelled by `kind` (counter).
pub const STORE_MERGE_MALFORMED_TOTAL: &str = "store_merge_malformed_total";

// ── HogVM executor (PR 1.4) ───────────────────────────────────────────────────
/// A cohort bytecode invoked a `CALL_GLOBAL`/symbol with no registered Rust native — i.e.
/// the M0 survey missed it. Labelled by `name`; a non-zero value means a cohort may be
/// silently evaluating to `false` (counter).
pub const STAGE1_HOGVM_UNKNOWN_FUNCTION: &str = "stage1_hogvm_unknown_function_total";
/// Any other VM/program failure during cohort evaluation, coerced to `false` (counter).
pub const STAGE1_HOGVM_ERROR: &str = "stage1_hogvm_error_total";
/// `properties`/`person_properties` JSON parse failure; the event is skipped, matching Node
/// (consumer.ts:200). Labelled by `field` (counter).
pub const STAGE1_GLOBALS_PARSE_ERROR: &str = "stage1_globals_parse_error_total";

// ── Partition routing (PR 1.5) ─────────────────────────────────────────────────
/// Partitions with a live worker channel registered on the router (gauge). Re-set on every
/// `add_partition` / `remove_partition`, so it tracks the worker-affinity fan-out width.
pub const PARTITIONS_ACTIVE: &str = "partitions_active";
/// Messages dropped while routing because the target partition had no live worker — almost
/// always a partition revoked mid-rebalance, or a worker that dropped its receiver. Labelled by
/// `reason` (counter). A sustained non-zero rate outside rebalances means routing is losing work.
pub const PARTITION_ROUTE_DROPPED_TOTAL: &str = "partition_route_dropped_total";
/// Sub-batches queued in a partition worker's channel, measured send-side as
/// `buffer − available_capacity`. Labelled by `partition` (gauge). The router's view of
/// per-partition backpressure; rising depth means a worker is falling behind the consumer.
pub const PARTITION_CHANNEL_DEPTH: &str = "partition_channel_depth";

// ── Stage 1 worker (PR 1.6) ────────────────────────────────────────────────────
/// Events the worker fully processed (passed preflight + applied state). Together with
/// [`STAGE1_EVENTS_SKIPPED`] this accounts for every event the worker dequeued (counter).
pub const STAGE1_EVENTS_PROCESSED: &str = "stage1_events_processed_total";
/// Events skipped whole, labelled by `reason`
/// (`null_person_id`|`unparseable_person_id`|`no_team_filters`|`no_conditions`|
/// `globals_parse_error`|`bad_timestamp`) (counter).
pub const STAGE1_EVENTS_SKIPPED: &str = "stage1_events_skipped_total";
/// HogVM evaluations performed, labelled by `kind` (`behavioral`|`person_property`) — one per
/// unique conditionHash per event, preserving the Node consumer's dedup unit (counter).
pub const STAGE1_CONDITIONS_EVALUATED: &str = "stage1_conditions_evaluated_total";
/// Leaf membership flips emitted, labelled by `kind`
/// (`behavioral_entered`|`person_entered`|`person_left`). `behavioral_left` is intentionally
/// omitted until sweep eviction (PR 2.2–2.3) so it cannot appear prematurely (counter).
pub const STAGE1_TRANSITIONS: &str = "stage1_transitions_total";
/// `cf_stage1` records written, labelled by `variant` (counter).
pub const STAGE1_STATE_WRITES: &str = "stage1_state_writes_total";
/// First-time `cf_person_index` appends (one per newly-seen `(person, leaf_state_key)`) (counter).
pub const STAGE1_PERSON_INDEX_APPENDS: &str = "stage1_person_index_appends_total";
/// Per-key applies skipped because the source `(partition, offset)` was already folded in — Kafka
/// replay idempotence. Labelled by `variant` (counter).
pub const STAGE1_REPLAY_SKIPPED: &str = "stage1_replay_skipped_total";
/// Person-property applies dropped by the event-time argMax tiebreaker (an out-of-order event
/// older than the last write) (counter).
pub const STAGE1_ARGMAX_STALE: &str = "stage1_argmax_stale_total";
/// Applies skipped because the leaf's resolved variant is not one PR 1.6 can apply — a
/// belt-and-suspenders guard against a stale catalog once PR 2.1 lands. Labelled by `variant`
/// (counter).
pub const STAGE1_UNSUPPORTED_VARIANT_SKIPPED: &str = "stage1_unsupported_variant_skipped_total";
/// Stored `cf_stage1` values that failed to decode; the offending key is skipped, never panicked
/// (counter).
pub const STAGE1_STATE_DECODE_ERROR: &str = "stage1_state_decode_error_total";
/// End-to-end per-event processing latency in the worker (histogram, seconds).
pub const STAGE1_EVENT_PROCESS_DURATION: &str = "stage1_event_process_duration_seconds";

/// Install the global Prometheus recorder. Call once at startup.
///
/// # Panics
/// Panics if a global metrics recorder has already been installed.
pub fn install_recorder() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("failed to install Prometheus recorder")
}
