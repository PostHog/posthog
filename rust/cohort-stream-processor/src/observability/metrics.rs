//! Prometheus recorder setup and the metric-name constants every emitter shares.

use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

/// Teams with ≥1 realtime cohort in the current catalog snapshot (gauge).
pub const FILTER_CATALOG_TEAMS: &str = "filter_catalog_teams";
/// Distinct `conditionHash`es across all teams in the current snapshot (gauge).
pub const FILTER_CATALOG_UNIQUE_CONDITIONS: &str = "filter_catalog_unique_conditions";
/// Leaves dropped during parse, labelled by `reason` (counter).
pub const FILTER_CATALOG_SKIPPED_LEAVES: &str = "filter_catalog_skipped_leaves_total";
/// Cohorts skipped because their filter tree failed to parse (counter).
pub const FILTER_CATALOG_COHORT_PARSE_ERRORS: &str = "filter_catalog_cohort_parse_errors_total";
/// Teams whose timezone did not parse as an IANA zone and fell back to UTC (counter).
pub const FILTER_CATALOG_TZ_FALLBACK: &str = "filter_catalog_tz_fallback_total";

/// Cohorts classified by composition eligibility at freeze, labelled by `class` (counter).
pub const COHORT_ELIGIBILITY_TOTAL: &str = "cohort_eligibility_total";
/// Cohorts excluded because they sit in a cohort-reference cycle (counter).
pub const COHORT_IN_CYCLE_TOTAL: &str = "cohort_in_cycle_total";

/// Cascade depths reached, from the `depth` field on cascade messages, labelled by
/// `originating_cohort_id` (histogram).
pub const CASCADE_DEPTH_OBSERVED: &str = "cascade_depth_observed";
/// Outgoing cascades dropped because `incoming.depth >= cohort_cascade_depth_cap`, labelled by
/// `originating_cohort_id` (counter).
pub const CASCADE_DEPTH_EXCEEDED_TOTAL: &str = "cascade_depth_exceeded_total";
/// Cycles caught at runtime by the `cascade_chain` membership check, labelled by
/// `originating_cohort_id`, `cycle_cohort_id` (counter). Distinct from [`COHORT_IN_CYCLE_TOTAL`],
/// which is Tarjan-SCC-based at catalog-refresh time.
pub const CASCADE_CYCLE_DETECTED_RUNTIME_TOTAL: &str = "cascade_cycle_detected_runtime_total";
/// Referrer re-evaluations dropped past `cohort_cascade_fanout_cap`, labelled by `upstream_cohort_id`
/// (counter).
pub const CASCADE_FANOUT_CAPPED_TOTAL: &str = "cascade_fanout_capped_total";

/// `(cohort, person)` pairs re-evaluated by Stage 2 composition (counter).
pub const STAGE2_COHORTS_EVALUATED: &str = "stage2_cohorts_evaluated_total";
/// Composable-cohort membership flips, labelled by `kind` (`entered`|`left`) (counter).
pub const STAGE2_TRANSITIONS: &str = "stage2_transitions_total";
/// Stage 2 decode failures (counter). The leaf reads as a non-member.
pub const STAGE2_STATE_DECODE_ERROR: &str = "stage2_state_decode_error_total";
/// Cohort-reference leaves reached during composable evaluation (counter). Non-zero signals a bug.
pub const STAGE2_UNEXPECTED_COHORT_REF: &str = "stage2_unexpected_cohort_ref_total";

/// RocksDB batch commits, labelled by `op` (counter).
pub const STORE_WRITE_BATCH_TOTAL: &str = "store_write_batch_total";
/// Latency of a committed RocksDB write, labelled by `op` (histogram, seconds).
pub const STORE_WRITE_DURATION_SECONDS: &str = "store_write_duration_seconds";
/// RocksDB operations that returned an error, labelled by `op` (counter).
pub const STORE_ERRORS_TOTAL: &str = "store_errors_total";
/// Malformed inputs the `cf_person_index` merge operator skipped, labelled by `kind` (counter).
pub const STORE_MERGE_MALFORMED_TOTAL: &str = "store_merge_malformed_total";

/// Cohort bytecode invoked a symbol with no registered native, labelled by `name` (counter).
pub const STAGE1_HOGVM_UNKNOWN_FUNCTION: &str = "stage1_hogvm_unknown_function_total";
/// Any other VM/program failure during cohort evaluation, coerced to `false` (counter).
pub const STAGE1_HOGVM_ERROR: &str = "stage1_hogvm_error_total";
/// `properties`/`person_properties` JSON parse failure, labelled by `field` (counter).
pub const STAGE1_GLOBALS_PARSE_ERROR: &str = "stage1_globals_parse_error_total";

/// Partitions with a live worker channel registered on the router (gauge).
pub const PARTITIONS_ACTIVE: &str = "partitions_active";
/// Messages dropped while routing (no live worker), labelled by `reason` (counter).
pub const PARTITION_ROUTE_DROPPED_TOTAL: &str = "partition_route_dropped_total";
/// Sub-batches queued in a partition worker's channel, labelled by `partition` (gauge).
pub const PARTITION_CHANNEL_DEPTH: &str = "partition_channel_depth";

/// Non-empty rebalance callbacks, labelled by `event_type` (`assign`|`revoke`) (counter).
pub const REBALANCES_TOTAL: &str = "rebalances_total";
/// Partitions assigned to this consumer across all rebalances (counter).
pub const PARTITIONS_ASSIGNED_TOTAL: &str = "partitions_assigned_total";
/// Partitions revoked from this consumer across all rebalances (counter).
pub const PARTITIONS_REVOKED_TOTAL: &str = "partitions_revoked_total";
/// Empty rebalance callbacks short-circuited, labelled by `event_type` (counter).
pub const REBALANCE_EMPTY_SKIPPED_TOTAL: &str = "rebalance_empty_skipped_total";
/// Per-partition revoke drain latency (histogram, seconds).
pub const REVOKE_DRAIN_DURATION_SECONDS: &str = "revoke_drain_duration_seconds";
/// Per-partition RocksDB state slices reclaimed on revoke (counter).
pub const PARTITION_STATE_DELETED_TOTAL: &str = "partition_state_deleted_total";
/// Revoke cleanups skipped because the partition was re-acquired, labelled by `phase` (counter).
pub const REBALANCE_CLEANUP_SKIPPED_TOTAL: &str = "rebalance_cleanup_skipped_total";

/// Events fully processed (counter).
pub const STAGE1_EVENTS_PROCESSED: &str = "stage1_events_processed_total";
/// Events skipped whole, labelled by `reason` (counter).
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

/// Envelopes consumed and successfully deserialized from `cohort_stream_events` (counter).
pub const COHORT_STREAM_EVENTS_CONSUMED: &str = "cohort_stream_events_consumed_total";
/// Events routed to a per-partition worker (counter). Conservation:
/// `consumed == dispatched + not_owned_skipped`.
pub const COHORT_STREAM_EVENTS_DISPATCHED: &str = "cohort_stream_events_dispatched_total";
/// Events dropped because the partition is no longer owned or shutdown is draining (counter).
pub const COHORT_STREAM_EVENTS_SKIPPED_NOT_OWNED: &str =
    "cohort_stream_events_skipped_not_owned_total";
/// Merge messages dropped because the partition is no longer owned or shutdown is draining (counter).
pub const COHORT_STREAM_MERGES_SKIPPED_NOT_OWNED: &str =
    "cohort_stream_merges_skipped_not_owned_total";
/// `KAFKA_PERSON_MERGE_EVENTS` envelopes consumed and successfully decoded (counter).
pub const COHORT_STREAM_MERGES_CONSUMED: &str = "cohort_stream_merges_consumed_total";
/// `cohort_merge_state_transfer` envelopes consumed and successfully decoded (counter).
pub const COHORT_STREAM_TRANSFERS_CONSUMED: &str = "cohort_stream_transfers_consumed_total";
/// `KAFKA_PERSON_MERGE_EVENTS` payloads that were empty or failed to decode (counter).
pub const COHORT_STREAM_MERGE_DESERIALIZE_ERRORS: &str =
    "cohort_stream_merge_deserialize_errors_total";
/// `cohort_merge_state_transfer` payloads that were empty or failed to decode (counter).
pub const COHORT_STREAM_TRANSFER_DESERIALIZE_ERRORS: &str =
    "cohort_stream_transfer_deserialize_errors_total";
/// Transfer messages dropped because the partition is no longer owned or shutdown is draining
/// (counter).
pub const COHORT_STREAM_TRANSFERS_SKIPPED_NOT_OWNED: &str =
    "cohort_stream_transfers_skipped_not_owned_total";
/// Decoded `KAFKA_PERSON_MERGE_EVENTS` envelopes accumulated per consume → dispatch cycle
/// (histogram). A separate constant per topic, not a label.
pub const COHORT_STREAM_MERGES_CONSUME_BATCH_SIZE: &str = "cohort_stream_merges_consume_batch_size";
/// Decoded `cohort_merge_state_transfer` envelopes accumulated per consume → dispatch cycle
/// (histogram).
pub const COHORT_STREAM_TRANSFERS_CONSUME_BATCH_SIZE: &str =
    "cohort_stream_transfers_consume_batch_size";
/// A worker tried to mark an offset past what the dispatcher routed (counter).
pub const COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH: &str =
    "cohort_stream_offset_ahead_of_dispatch_total";
/// Messages with a present-but-unparseable payload (counter).
pub const COHORT_STREAM_DESERIALIZE_ERRORS: &str = "cohort_stream_deserialize_errors_total";
/// Messages with a `None` (zero-byte) payload, skipped (counter).
pub const COHORT_STREAM_EMPTY_PAYLOAD: &str = "cohort_stream_empty_payload_total";
/// Kafka transport errors from `recv()` (counter).
pub const COHORT_STREAM_KAFKA_RECV_ERRORS: &str = "cohort_stream_kafka_recv_errors_total";
/// Offset commits accepted by Kafka (counter).
pub const COHORT_STREAM_OFFSET_COMMITS: &str = "cohort_stream_offset_commits_total";
/// Offset commit attempts Kafka rejected (counter).
pub const COHORT_STREAM_OFFSET_COMMIT_ERRORS: &str = "cohort_stream_offset_commit_errors_total";
/// Stage 1 workers lazily spawned on first delivery of a partition (counter).
pub const COHORT_STREAM_WORKERS_SPAWNED: &str = "cohort_stream_workers_spawned_total";
/// Per-partition routing failures (counter).
pub const COHORT_STREAM_ROUTE_ERRORS: &str = "cohort_stream_route_errors_total";
/// Events accumulated per consume → route cycle (histogram).
pub const COHORT_STREAM_CONSUME_BATCH_SIZE: &str = "cohort_stream_consume_batch_size";

/// Membership changes produced to `cohort_membership_changed_shadow`, labelled by `status`
/// (counter). Counted only after a fully-acked flush.
pub const OUTPUT_MEMBERSHIP_CHANGES_EMITTED: &str = "output_membership_changes_emitted_total";
/// Leaf transitions that mapped to zero output cohorts, labelled by `reason` (counter).
pub const OUTPUT_TRANSITIONS_UNMAPPED: &str = "output_transitions_unmapped_total";
/// Produce failures to `cohort_membership_changed_shadow` (counter).
pub const OUTPUT_PRODUCE_ERRORS: &str = "output_produce_errors_total";

/// Sweep cycles that fired, labelled by `loop` (`eviction`|`redrive`|`merge_gc`) (counter).
pub const SWEEP_CYCLES_TOTAL: &str = "sweep_cycles_total";
/// Wall-clock duration of one sweep cycle, labelled by `loop` (histogram, seconds).
pub const SWEEP_CYCLE_DURATION_SECONDS: &str = "sweep_cycle_duration_seconds";
/// Keys the sweep evicted, labelled by `variant` (counter).
pub const SWEEP_KEYS_EVICTED_TOTAL: &str = "sweep_keys_evicted_total";
/// Person merges handled, labelled by `path` (`same_partition`|`cross_partition`) (counter).
pub const MERGE_HANDLED_TOTAL: &str = "merge_handled_total";
/// Drain messages short-circuited by a `cf_merge_drains_applied` hit (counter).
pub const MERGE_DRAINS_SKIPPED_REPLAY_TOTAL: &str = "merge_drains_skipped_replay_total";
/// Transfer messages short-circuited by a `cf_merge_applied` hit (counter).
pub const MERGE_APPLIES_SKIPPED_REPLAY_TOTAL: &str = "merge_applies_skipped_replay_total";
/// Late events for merged persons that triggered a tombstone redirect, labelled by `path`
/// (`inline`|`re_keyed`) (counter). `inline` counts at resolve time; `re_keyed` counts only after
/// the re-produce ack. A hop-capped redirect is counted only under
/// [`MERGE_REDIRECT_HOP_CAPPED_TOTAL`].
pub const MERGE_TOMBSTONE_REDIRECTS_TOTAL: &str = "merge_tombstone_redirects_total";
/// Straggler re-key produces to `cohort_stream_events` that failed (counter).
pub const MERGE_REKEY_PRODUCE_FAILURE_TOTAL: &str = "merge_rekey_produce_failure_total";
/// Cross-partition redirects that hit the `redirect_hops` cap and were processed inline (counter).
/// Non-zero means a corrupt tombstone cycle.
pub const MERGE_REDIRECT_HOP_CAPPED_TOTAL: &str = "merge_redirect_hop_capped_total";
/// State transfers re-targeted at apply time because `new_person_uuid` was itself tombstoned (a
/// chained merge `A → B → C` where `B → C` drained before `A → B` applied), labelled by `path`
/// (`inline`|`re_keyed`). `inline` = the resolved survivor co-resides on this partition and the
/// transfer applied there directly; `re_keyed` = the survivor lives on another partition and the
/// transfer was forwarded on `cohort_merge_state_transfer`, counted only after the forward ack.
pub const MERGE_TRANSFER_FORWARDS_TOTAL: &str = "merge_transfer_forwards_total";
/// Transfer forwards that hit the [`crate::merge::apply_handler::MAX_TRANSFER_FORWARD_HOPS`] cap and
/// were not forwarded (counter). Non-zero means a corrupt tombstone cycle, same class as
/// [`MERGE_REDIRECT_HOP_CAPPED_TOTAL`].
pub const MERGE_FORWARD_HOP_CAPPED_TOTAL: &str = "merge_forward_hop_capped_total";
/// Per-leaf merge work dropped, labelled by `reason` (counter).
pub const MERGE_LEAVES_DROPPED_TOTAL: &str = "merge_leaves_dropped_total";
/// Transfer produces that exhausted the inline retry budget (counter). The packaged state stays in
/// `cf_pending_transfers` and the merge offset is not committed; the periodic redrive closes the
/// gap.
pub const MERGE_TRANSFER_PRODUCE_FAILURE_TOTAL: &str = "merge_transfer_produce_failure_total";
/// `cf_pending_transfers` clears that failed after the transfer produce was acked (counter). The
/// merge offset still commits; the leftover outbox entry only re-produces a duplicate the apply
/// side's dedup absorbs.
pub const MERGE_OUTBOX_CLEAR_FAILURE_TOTAL: &str = "merge_outbox_clear_failure_total";
/// Cross-partition drains whose packaged transfer carried no leaves (counter).
pub const MERGE_TRANSFERS_SKIPPED_EMPTY_TOTAL: &str = "merge_transfers_skipped_empty_total";
/// Entries currently staged in a partition's `cf_pending_transfers` outbox, labelled by `partition`
/// (gauge). A sustained non-zero level means the transfer topic keeps refusing produces.
pub const MERGE_PENDING_TRANSFERS_GAUGE: &str = "merge_pending_transfers";
/// The merge/transfer commit floor pinned by a sticky offset hold on a partition, labelled by
/// `partition` (gauge). A non-zero value means a failed merge drain / transfer apply is holding the
/// partition's committable offset for redelivery and will not advance until the next tenure replays
/// it — a *visible* commit-stall, by design, in place of silent merge/transfer state loss. **Alert on
/// a sustained non-zero level**: a persistent store error re-fails every tenure and lag grows.
pub const MERGE_HELD_OFFSET_GAUGE: &str = "merge_held_offset";
/// Latency of one merge drain (histogram, seconds).
pub const MERGE_DRAIN_DURATION_SECONDS: &str = "merge_drain_duration_seconds";
/// Latency of one transfer apply (histogram, seconds).
pub const MERGE_APPLY_DURATION_SECONDS: &str = "merge_apply_duration_seconds";

/// Merge-CF keys scanned by the GC sweep, labelled by `cf` (counter).
pub const MERGE_GC_KEYS_SCANNED_TOTAL: &str = "merge_gc_keys_scanned_total";
/// Merge-CF keys the GC sweep deleted (expired or undecodable), labelled by `cf` (counter).
pub const MERGE_GC_KEYS_DELETED_TOTAL: &str = "merge_gc_keys_deleted_total";
/// Merge-CF values the GC sweep could not decode, labelled by `cf` (counter). Each is deleted and
/// folded into [`MERGE_GC_KEYS_DELETED_TOTAL`] (an unreadable timestamp can never age out).
pub const MERGE_GC_UNDECODABLE_TOTAL: &str = "merge_gc_undecodable_total";

/// Keys the sweep popped but did not evict, labelled by `reason` (counter). Conservation:
/// `popped == evicted + dropped`.
pub const SWEEP_KEYS_DROPPED_TOTAL: &str = "sweep_keys_dropped_total";

/// Install the global Prometheus recorder. Call once at startup.
///
/// # Panics
/// Panics if a global metrics recorder has already been installed.
pub fn install_recorder() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("failed to install Prometheus recorder")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cascade_metric_names_are_stable() {
        // Pin the wire names: a rename must not silently break dashboards or alerts.
        assert_eq!(CASCADE_DEPTH_OBSERVED, "cascade_depth_observed");
        assert_eq!(CASCADE_DEPTH_EXCEEDED_TOTAL, "cascade_depth_exceeded_total");
        assert_eq!(
            CASCADE_CYCLE_DETECTED_RUNTIME_TOTAL,
            "cascade_cycle_detected_runtime_total",
        );
        assert_eq!(CASCADE_FANOUT_CAPPED_TOTAL, "cascade_fanout_capped_total");
    }
}
