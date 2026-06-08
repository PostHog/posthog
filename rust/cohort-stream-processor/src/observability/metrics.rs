//! Prometheus recorder setup and the metric-name constants every emitter shares.

use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

// ── Filter catalog ─────────────────────────────────────────────────────────────
/// Teams with ≥1 realtime cohort in the current catalog snapshot (gauge).
pub const FILTER_CATALOG_TEAMS: &str = "filter_catalog_teams";
/// Distinct `conditionHash`es across all teams in the current snapshot (gauge).
pub const FILTER_CATALOG_UNIQUE_CONDITIONS: &str = "filter_catalog_unique_conditions";
/// Leaves dropped during parse, labelled by `reason` (counter). Rebuild-driven (re-dropped every
/// refresh), so graph its rate, not its level.
pub const FILTER_CATALOG_SKIPPED_LEAVES: &str = "filter_catalog_skipped_leaves_total";
/// Cohorts skipped because their filter tree failed to parse (counter).
pub const FILTER_CATALOG_COHORT_PARSE_ERRORS: &str = "filter_catalog_cohort_parse_errors_total";
/// Teams whose `posthog_team.timezone` did not parse as an IANA zone and fell back to UTC (counter).
/// Label-free on purpose — the raw timezone string goes only to the `warn!`, never a metric label.
pub const FILTER_CATALOG_TZ_FALLBACK: &str = "filter_catalog_tz_fallback_total";

// ── Store ──────────────────────────────────────────────────────────────────────
/// RocksDB batch commits, labelled by `op` (counter).
pub const STORE_WRITE_BATCH_TOTAL: &str = "store_write_batch_total";
/// Latency of a committed RocksDB write, labelled by `op` (histogram, seconds).
pub const STORE_WRITE_DURATION_SECONDS: &str = "store_write_duration_seconds";
/// RocksDB operations that returned an error, labelled by `op` (counter).
pub const STORE_ERRORS_TOTAL: &str = "store_errors_total";
/// Malformed inputs the `cf_person_index` merge operator skipped, labelled by `kind` (counter).
/// Skipped rather than panicked because a panic on a compaction thread is FFI UB.
pub const STORE_MERGE_MALFORMED_TOTAL: &str = "store_merge_malformed_total";

// ── HogVM executor ─────────────────────────────────────────────────────────────
/// Cohort bytecode invoked a symbol with no registered Rust native, labelled by `name` (counter).
/// Non-zero means a cohort may be silently evaluating to `false`.
pub const STAGE1_HOGVM_UNKNOWN_FUNCTION: &str = "stage1_hogvm_unknown_function_total";
/// Any other VM/program failure during cohort evaluation, coerced to `false` (counter).
pub const STAGE1_HOGVM_ERROR: &str = "stage1_hogvm_error_total";
/// `properties`/`person_properties` JSON parse failure, labelled by `field` (counter). The event is
/// skipped, matching Node (consumer.ts:200).
pub const STAGE1_GLOBALS_PARSE_ERROR: &str = "stage1_globals_parse_error_total";

// ── Partition routing ──────────────────────────────────────────────────────────
/// Partitions with a live worker channel registered on the router (gauge).
pub const PARTITIONS_ACTIVE: &str = "partitions_active";
/// Messages dropped while routing because the target partition had no live worker, labelled by
/// `reason` (counter). Usually a partition revoked mid-rebalance.
pub const PARTITION_ROUTE_DROPPED_TOTAL: &str = "partition_route_dropped_total";
/// Sub-batches queued in a partition worker's channel, labelled by `partition` (gauge).
pub const PARTITION_CHANNEL_DEPTH: &str = "partition_channel_depth";

// ── Rebalance handling ─────────────────────────────────────────────────────────
/// Non-empty rebalance callbacks observed, labelled by `event_type` (`assign`|`revoke`) (counter).
/// One per callback; pairs with the per-partition [`PARTITIONS_ASSIGNED_TOTAL`] /
/// [`PARTITIONS_REVOKED_TOTAL`].
pub const REBALANCES_TOTAL: &str = "rebalances_total";
/// Partitions assigned to this consumer across all rebalances (counter).
pub const PARTITIONS_ASSIGNED_TOTAL: &str = "partitions_assigned_total";
/// Partitions revoked from this consumer across all rebalances (counter).
pub const PARTITIONS_REVOKED_TOTAL: &str = "partitions_revoked_total";
/// Empty rebalance callbacks short-circuited, labelled by `event_type` (counter). Cooperative-sticky
/// fires these whenever group membership changes without moving this consumer's partitions.
pub const REBALANCE_EMPTY_SKIPPED_TOTAL: &str = "rebalance_empty_skipped_total";
/// Per-partition revoke drain (worker join) latency (histogram, seconds). The drain produces and
/// acks the partition's tail before it is reclaimed.
pub const REVOKE_DRAIN_DURATION_SECONDS: &str = "revoke_drain_duration_seconds";
/// Per-partition RocksDB state slices reclaimed on revoke (counter). Pairs with
/// [`PARTITIONS_REVOKED_TOTAL`]; the gap is revokes that re-acquired before cleanup ran.
pub const PARTITION_STATE_DELETED_TOTAL: &str = "partition_state_deleted_total";
/// Revoke cleanups skipped because the partition was re-acquired before the wipe ran — the rapid
/// revoke→assign race (counter). Labelled by `phase`: `entry` (re-acquired before the drain started)
/// or `post_join` (re-acquired during the worker join, so the slice is preserved for the new tenure).
pub const REBALANCE_CLEANUP_SKIPPED_TOTAL: &str = "rebalance_cleanup_skipped_total";

// ── Stage 1 worker ─────────────────────────────────────────────────────────────
/// Events fully processed; with [`STAGE1_EVENTS_SKIPPED`] accounts for every dequeued event
/// (counter).
pub const STAGE1_EVENTS_PROCESSED: &str = "stage1_events_processed_total";
/// Events skipped whole, labelled by `reason` (counter). `store_error` is also counted in
/// `store_errors_total`; counting it here keeps `consumed == processed + Σskipped` exact.
pub const STAGE1_EVENTS_SKIPPED: &str = "stage1_events_skipped_total";
/// HogVM evaluations, labelled by `kind` — one per unique conditionHash per event (counter).
pub const STAGE1_CONDITIONS_EVALUATED: &str = "stage1_conditions_evaluated_total";
/// Leaf membership flips emitted, labelled by `kind` (counter).
pub const STAGE1_TRANSITIONS: &str = "stage1_transitions_total";
/// `cf_stage1` records written, labelled by `variant` (counter).
pub const STAGE1_STATE_WRITES: &str = "stage1_state_writes_total";
/// First-time `cf_person_index` appends, one per newly-seen `(person, leaf_state_key)` (counter).
pub const STAGE1_PERSON_INDEX_APPENDS: &str = "stage1_person_index_appends_total";
/// Applies skipped because the source `(partition, offset)` was already folded in, labelled by
/// `variant` (counter).
pub const STAGE1_REPLAY_SKIPPED: &str = "stage1_replay_skipped_total";
/// Person-property applies dropped by the event-time argMax tiebreaker (counter).
pub const STAGE1_ARGMAX_STALE: &str = "stage1_argmax_stale_total";
/// Applies skipped because the leaf's resolved variant is unsupported, labelled by `variant`
/// (counter). A defensive guard against a stale catalog.
pub const STAGE1_UNSUPPORTED_VARIANT_SKIPPED: &str = "stage1_unsupported_variant_skipped_total";
/// Stored `cf_stage1` values that failed to decode; the key is skipped, not panicked (counter).
pub const STAGE1_STATE_DECODE_ERROR: &str = "stage1_state_decode_error_total";
/// End-to-end per-event processing latency in the worker (histogram, seconds).
pub const STAGE1_EVENT_PROCESS_DURATION: &str = "stage1_event_process_duration_seconds";

// ── `cohort_stream_events` consumer ────────────────────────────────────────────
/// Envelopes consumed and successfully deserialized from `cohort_stream_events` (counter).
pub const COHORT_STREAM_EVENTS_CONSUMED: &str = "cohort_stream_events_consumed_total";
/// Events actually routed to a per-partition worker (counter). Counts only routed events — events
/// for a partition this consumer no longer owns are excluded (see
/// [`COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED`]). Conservation chain:
/// `consumed == dispatched + not_owned_skipped` and `dispatched == processed + Σskipped + route_errors`.
pub const COHORT_STREAM_EVENTS_DISPATCHED: &str = "cohort_stream_events_dispatched_total";
/// Events dropped in `dispatch` because this consumer no longer owns their partition (counter): a
/// revoke that raced an already-`recv()`'d in-flight batch. The event is never routed and never
/// marked processed, so Kafka replays it on the partition's true owner. Closes the consumer half of
/// the conservation chain: `consumed == dispatched + not_owned_skipped`.
pub const COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED: &str =
    "cohort_stream_events_skipped_not_owned_total";
/// A worker tried to mark an offset past what the dispatcher routed to it, so the
/// [`OffsetTracker`](crate::partitions::OffsetTracker) capped it (counter). A non-zero rate should
/// page.
pub const COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH: &str =
    "cohort_stream_offset_ahead_of_dispatch_total";
/// Messages with a present-but-unparseable payload; skipped, offset still advances (counter).
pub const COHORT_STREAM_DESERIALIZE_ERRORS: &str = "cohort_stream_deserialize_errors_total";
/// Messages with a `None` (zero-byte) payload, skipped (counter). Distinct from
/// [`COHORT_STREAM_DESERIALIZE_ERRORS`] so neither is a conservation blind spot.
pub const COHORT_STREAM_EMPTY_PAYLOAD: &str = "cohort_stream_empty_payload_total";
/// Kafka transport errors from `recv()` (counter). A sustained rate suppresses the liveness
/// heartbeat, so the stall detector eventually restarts the pod.
pub const COHORT_STREAM_KAFKA_RECV_ERRORS: &str = "cohort_stream_kafka_recv_errors_total";
/// Offset commits accepted by Kafka (counter).
pub const COHORT_STREAM_OFFSET_COMMITS: &str = "cohort_stream_offset_commits_total";
/// Offset commit attempts Kafka rejected; retried on the next tick (counter).
pub const COHORT_STREAM_OFFSET_COMMIT_ERRORS: &str = "cohort_stream_offset_commit_errors_total";
/// Stage 1 workers lazily spawned on first delivery of a partition (counter).
pub const COHORT_STREAM_WORKERS_SPAWNED: &str = "cohort_stream_workers_spawned_total";
/// Per-partition routing failures (no live worker / closed channel); the offset is held back so
/// Kafka replays it (counter).
pub const COHORT_STREAM_ROUTE_ERRORS: &str = "cohort_stream_route_errors_total";
/// Events accumulated per consume → route cycle (histogram).
pub const COHORT_STREAM_CONSUME_BATCH_SIZE: &str = "cohort_stream_consume_batch_size";

// ── Output producer ────────────────────────────────────────────────────────────
/// Membership changes produced to `cohort_membership_changed_shadow`, labelled by `status`
/// (counter). Counted only after a fully-acked flush.
pub const OUTPUT_MEMBERSHIP_CHANGES_EMITTED: &str = "output_membership_changes_emitted_total";
/// Leaf transitions that mapped to zero output cohorts, labelled by `reason` (counter). A single
/// leaf flip only determines a single-leaf cohort's membership.
pub const OUTPUT_TRANSITIONS_UNMAPPED: &str = "output_transitions_unmapped_total";
/// Produce failures to `cohort_membership_changed_shadow` (counter). The worker holds the offset
/// back so Kafka replays; re-produce is idempotent for the parity diff.
pub const OUTPUT_PRODUCE_ERRORS: &str = "output_produce_errors_total";

// ── Sweep (time-driven eviction) ─────────────────────────────────────────────────
/// Sweep cycles that fired (counter). One per [`run_sweep_loop`](crate::sweep::run_sweep_loop) tick;
/// ticks skipped under lag (`MissedTickBehavior::Skip`) are not counted, so graph its rate against
/// `sweep_interval` to spot a starved sweep.
pub const SWEEP_CYCLES_TOTAL: &str = "sweep_cycles_total";
/// Wall-clock duration of one sweep cycle (histogram, seconds): how long a single
/// [`Sweeper::run_once`](crate::sweep::Sweeper::run_once) took.
pub const SWEEP_CYCLE_DURATION_SECONDS: &str = "sweep_cycle_duration_seconds";
/// Keys the sweep evicted — state deleted (full expiry) or its window advanced — labelled by
/// `variant` (counter). The `Left`s and `Entered`s these emit reuse
/// `output_membership_changes_emitted_total{status}` and `stage1_transitions_total`, so this counts
/// eviction *work*, not just membership flips (a daily slide that drops a bucket but keeps the member
/// is counted here with no transition).
pub const SWEEP_KEYS_EVICTED_TOTAL: &str = "sweep_keys_evicted_total";

/// Install the global Prometheus recorder. Call once at startup.
///
/// # Panics
/// Panics if a global metrics recorder has already been installed.
pub fn install_recorder() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("failed to install Prometheus recorder")
}
