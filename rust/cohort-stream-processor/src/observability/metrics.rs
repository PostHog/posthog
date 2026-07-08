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

/// Cascade depths reached, from the `depth` field on cascade messages (histogram). Cohort ids are
/// logged, not labelled, to keep cardinality bounded.
pub const CASCADE_DEPTH_OBSERVED: &str = "cascade_depth_observed";
/// Outgoing cascades dropped because `incoming.depth >= cohort_cascade_depth_cap` (counter). Cohort
/// ids are logged, not labelled, to keep cardinality bounded.
pub const CASCADE_DEPTH_EXCEEDED_TOTAL: &str = "cascade_depth_exceeded_total";
/// Cycles caught at runtime by the `cascade_chain` membership check (counter). Cohort ids are
/// logged, not labelled, to keep cardinality bounded. Distinct from [`COHORT_IN_CYCLE_TOTAL`], which
/// is Tarjan-SCC-based at catalog-refresh time.
pub const CASCADE_CYCLE_DETECTED_RUNTIME_TOTAL: &str = "cascade_cycle_detected_runtime_total";
/// Referrer re-evaluations dropped past `cohort_cascade_fanout_cap` (counter). Cohort ids are
/// logged, not labelled, to keep cardinality bounded.
pub const CASCADE_FANOUT_CAPPED_TOTAL: &str = "cascade_fanout_capped_total";
/// First-hop or onward cascade produces to `cohort_cascade_events` that failed (counter). On the
/// event path a failure holds the batch; on the sweep/merge paths it drops (at-most-once).
pub const CASCADE_PRODUCE_ERRORS_TOTAL: &str = "cascade_produce_errors_total";
/// The cascade-consumer commit floor pinned by a sticky offset hold, labelled by `partition` (gauge).
/// Non-zero means a held cascade re-evaluation is stalling the commit. **Alert on a sustained
/// non-zero level.**
pub const CASCADE_HELD_OFFSET_GAUGE: &str = "cascade_held_offset";

/// `(cohort, person)` pairs re-evaluated by Stage 2 composition (counter).
pub const STAGE2_COHORTS_EVALUATED: &str = "stage2_cohorts_evaluated_total";
/// Composable-cohort membership flips, labelled by `kind` (`entered`|`left`) (counter).
pub const STAGE2_TRANSITIONS: &str = "stage2_transitions_total";
/// Stage 2 decode failures (counter). The leaf reads as a non-member.
pub const STAGE2_STATE_DECODE_ERROR: &str = "stage2_state_decode_error_total";
/// Cohort-reference leaves reached during composable evaluation (counter). Non-zero signals a bug.
pub const STAGE2_UNEXPECTED_COHORT_REF: &str = "stage2_unexpected_cohort_ref_total";

/// Latency of one synchronous WAL fsync before an offset commit (histogram, seconds). Amortized over
/// a batch of writes — it runs on the commit deadline, not per-message.
pub const WAL_FSYNC_DURATION_SECONDS: &str = "wal_fsync_duration_seconds";
/// WAL fsyncs that returned an error (counter). The commit is then skipped, so a persistent failure
/// surfaces as growing consumer lag. **Alert on a sustained non-zero level.**
pub const WAL_FSYNC_ERRORS_TOTAL: &str = "wal_fsync_errors_total";

/// On-disk partition slices kept (reopen-live) across a durable restart, because still assigned to
/// this pod (counter).
pub const DURABLE_RESTORE_PARTITIONS_KEPT_TOTAL: &str = "durable_restore_partitions_kept_total";
/// On-disk partition slices wiped because no longer assigned to this pod — stale state to cold-rebuild
/// from the committed offset (counter).
pub const DURABLE_RESTORE_PARTITIONS_WIPED_STALE_TOTAL: &str =
    "durable_restore_partitions_wiped_stale_total";
/// `cf_behavioral` keys re-seeded into a worker's `EvictionQueue` on spawn during a durable restart,
/// labelled by `partition` (counter). Re-fires a dormant person's `Left`.
pub const EVICTION_QUEUE_REBUILT_KEYS_TOTAL: &str = "eviction_queue_rebuilt_keys_total";
/// Owned partitions that had at least one `cf_pending_transfers` entry re-produced by the eager boot
/// redrive on a durable restart (counter). Incremented once per partition that recovered ≥1 transfer.
pub const DURABLE_RESTORE_PENDING_TRANSFERS_RECOVERED_PARTITIONS_TOTAL: &str =
    "durable_restore_pending_transfers_recovered_partitions_total";

/// Wall-clock duration of one whole-DB `Checkpoint::create_checkpoint` (histogram, seconds).
/// Whole-DB checkpoint, so these are per-pod, not per-partition.
pub const CHECKPOINT_DURATION_SECONDS: &str = "checkpoint_duration_seconds";
/// On-disk size of a freshly-taken checkpoint directory (histogram, bytes).
pub const CHECKPOINT_SIZE_BYTES: &str = "checkpoint_size_bytes";
/// File count in a freshly-taken checkpoint directory (histogram).
pub const CHECKPOINT_FILE_COUNT: &str = "checkpoint_file_count";
/// Checkpoint S3 uploads, labelled by `result` (`success`|`error`|`cancelled`|`unavailable`); when
/// `result=cancelled`, an additional `cause` label (`rebalance`|`shutdown`|`unknown`) (counter).
pub const CHECKPOINT_UPLOADS_TOTAL: &str = "checkpoint_uploads_total";
/// Wall-clock duration of one checkpoint S3 upload, labelled by `result` (histogram, seconds).
pub const CHECKPOINT_UPLOAD_DURATION_SECONDS: &str = "checkpoint_upload_duration_seconds";
/// Individual checkpoint files uploaded to S3, labelled by `status` (`success`|`error`|`cancelled`)
/// (counter).
pub const CHECKPOINT_FILES_UPLOADED_TOTAL: &str = "checkpoint_files_uploaded_total";
/// Individual checkpoint files downloaded from S3, labelled by `status`
/// (`success`|`error`|`cancelled`) (counter).
pub const CHECKPOINT_FILES_DOWNLOADED_TOTAL: &str = "checkpoint_files_downloaded_total";
/// Files seen during incremental checkpoint planning, labelled by `action`
/// (`added`|`replaced`|`retained`) (counter).
pub const CHECKPOINT_PLAN_FILES_TOTAL: &str = "checkpoint_plan_files_total";
/// Latency of one metadata.json fetch from S3 into memory (histogram, seconds).
pub const CHECKPOINT_FILE_FETCH_DURATION_SECONDS: &str = "checkpoint_file_fetch_duration_seconds";
/// Latency of fetching a whole checkpoint's files to disk (the parallel fanout) (histogram, seconds).
pub const CHECKPOINT_FILES_FETCH_DURATION_SECONDS: &str = "checkpoint_files_fetch_duration_seconds";
/// Latency of fetching and storing a single checkpoint file to disk (histogram, seconds).
pub const CHECKPOINT_FILE_FETCH_STORE_DURATION_SECONDS: &str =
    "checkpoint_file_fetch_store_duration_seconds";
/// Latency of listing a checkpoint's recent attempt folders from S3 (histogram, seconds).
pub const CHECKPOINT_LIST_DURATION_SECONDS: &str = "checkpoint_list_duration_seconds";
/// Boot restores, labelled by `source` (`reopen_live`|`pvc`|`s3`|`cold`) (counter).
pub const CHECKPOINT_RESTORE_TOTAL: &str = "checkpoint_restore_total";
/// Wall-clock duration of one boot restore (histogram, seconds).
pub const CHECKPOINT_RESTORE_DURATION_SECONDS: &str = "checkpoint_restore_duration_seconds";
/// End-to-end checkpoint import (list + metadata + files + fallbacks), labelled by `result`
/// (`success`|`failed`|`cancelled`|`timeout`) (histogram, seconds).
pub const CHECKPOINT_IMPORT_DURATION_SECONDS: &str = "checkpoint_import_duration_seconds";
/// Duration of one import attempt (one checkpoint's files), labelled by `result`
/// (`success`|`failed`) (histogram, seconds).
pub const CHECKPOINT_IMPORT_ATTEMPT_DURATION_SECONDS: &str =
    "checkpoint_import_attempt_duration_seconds";

/// RocksDB batch commits, labelled by `op` (counter).
pub const STORE_WRITE_BATCH_TOTAL: &str = "store_write_batch_total";
/// Latency of a committed RocksDB write, labelled by `op` (histogram, seconds).
pub const STORE_WRITE_DURATION_SECONDS: &str = "store_write_duration_seconds";
/// RocksDB operations that returned an error, labelled by `op` (counter).
pub const STORE_ERRORS_TOTAL: &str = "store_errors_total";
/// Stores destroyed and recreated at open because the on-disk schema version did not match, under the
/// `COHORT_WIPE_ON_SCHEMA_MISMATCH` opt-in (counter). Non-zero means a store layout revision wiped
/// durable state; expected only on a deliberate schema migration.
pub const STORE_SCHEMA_MISMATCH_WIPES_TOTAL: &str = "store_schema_mismatch_wipes_total";

/// Time an offloaded store op waited to acquire its read-lane permit on the async side, before it
/// was ever spawned, labelled by `op` (histogram, seconds). Recorded only when the lane is bounded.
pub const STORE_OFFLOAD_PERMIT_WAIT_DURATION_SECONDS: &str =
    "store_offload_permit_wait_duration_seconds";
/// Time from `spawn_blocking` to the offloaded closure actually starting, labelled by `op`
/// (histogram, seconds) — the blocking-pool queue wait plus spawn overhead.
pub const STORE_OFFLOAD_QUEUE_WAIT_DURATION_SECONDS: &str =
    "store_offload_queue_wait_duration_seconds";
/// Execution time of the offloaded op inside the blocking closure, labelled by `op` (histogram,
/// seconds) — excludes permit and queue waits, so it is the pure on-thread store cost.
pub const STORE_OFFLOAD_EXEC_DURATION_SECONDS: &str = "store_offload_exec_duration_seconds";
/// Store ops currently executing inside a blocking closure, labelled by `lane`
/// (`event`|`maintenance`|`write`|`section`) (gauge). Maintained inside the closure so it stays
/// correct even if the caller future is dropped mid-flight.
pub const STORE_OFFLOAD_INFLIGHT: &str = "store_offload_inflight";

/// Latency of a RocksDB read, labelled by `op` (histogram, seconds). `op=get` is sampled 1-in-N
/// (`StoreConfig::read_sample_ratio`) — use [`STORE_READS_TOTAL`] for exact volume. `op=multi_get`
/// records once per batch.
pub const STORE_READ_DURATION_SECONDS: &str = "store_read_duration_seconds";
/// Logical RocksDB reads issued, labelled by `op` (counter). A `multi_get` counts once per key.
pub const STORE_READS_TOTAL: &str = "store_reads_total";

/// Block-cache hits across all block types (counter, cumulative since store open).
pub const STORE_BLOCK_CACHE_HITS_TOTAL: &str = "store_block_cache_hits_total";
/// Block-cache misses across all block types (counter, cumulative since store open).
pub const STORE_BLOCK_CACHE_MISSES_TOTAL: &str = "store_block_cache_misses_total";
/// Data-block cache hits (counter, cumulative since store open).
pub const STORE_BLOCK_CACHE_DATA_HITS_TOTAL: &str = "store_block_cache_data_hits_total";
/// Data-block cache misses (counter, cumulative since store open).
pub const STORE_BLOCK_CACHE_DATA_MISSES_TOTAL: &str = "store_block_cache_data_misses_total";
/// Index-block cache hits (counter, cumulative since store open).
pub const STORE_BLOCK_CACHE_INDEX_HITS_TOTAL: &str = "store_block_cache_index_hits_total";
/// Index-block cache misses (counter, cumulative since store open).
pub const STORE_BLOCK_CACHE_INDEX_MISSES_TOTAL: &str = "store_block_cache_index_misses_total";
/// Filter-block (bloom) cache hits (counter, cumulative since store open).
pub const STORE_BLOCK_CACHE_FILTER_HITS_TOTAL: &str = "store_block_cache_filter_hits_total";
/// Filter-block (bloom) cache misses (counter, cumulative since store open).
pub const STORE_BLOCK_CACHE_FILTER_MISSES_TOTAL: &str = "store_block_cache_filter_misses_total";
/// Point lookups the bloom filter let skip a data-block read (counter, cumulative since store open).
pub const STORE_BLOOM_FILTER_USEFUL_TOTAL: &str = "store_bloom_filter_useful_total";

/// Bytes the shared block cache currently holds (gauge).
pub const STORE_BLOCK_CACHE_USAGE_BYTES: &str = "store_block_cache_usage_bytes";
/// On-disk SST bytes, labelled by `cf` (gauge).
pub const STORE_SST_BYTES: &str = "store_sst_bytes";
/// Estimated live (non-tombstone) data bytes, labelled by `cf` (gauge).
pub const STORE_LIVE_DATA_BYTES: &str = "store_live_data_bytes";
/// Estimated key count, labelled by `cf` (gauge).
pub const STORE_ESTIMATE_NUM_KEYS: &str = "store_estimate_num_keys";

/// Fraction of wall-clock worker-time spent executing tasks (gauge, 0.0–1.0).
pub const TOKIO_RUNTIME_BUSY_RATIO: &str = "tokio_runtime_busy_ratio";
/// Tasks spawned but not yet completed on the runtime (gauge).
pub const TOKIO_RUNTIME_ALIVE_TASKS: &str = "tokio_runtime_alive_tasks";
/// Tasks pending in the runtime's global injection queue (gauge).
pub const TOKIO_RUNTIME_GLOBAL_QUEUE_DEPTH: &str = "tokio_runtime_global_queue_depth";
/// Configured Tokio worker threads (gauge).
pub const TOKIO_RUNTIME_NUM_WORKERS: &str = "tokio_runtime_num_workers";
/// Per-worker busy time over the sample interval, labelled by `worker` (gauge, seconds).
pub const TOKIO_WORKER_BUSY_DURATION_DELTA: &str = "tokio_worker_busy_duration_delta_secs";
/// Per-worker park-count delta over the sample interval, labelled by `worker` (gauge).
pub const TOKIO_WORKER_PARK_DELTA: &str = "tokio_worker_park_delta";
/// Per-worker poll-count delta over the sample interval, labelled by `worker` (gauge).
pub const TOKIO_WORKER_POLL_DELTA: &str = "tokio_worker_poll_delta";
/// Per-worker steal-count delta over the sample interval, labelled by `worker` (gauge).
pub const TOKIO_WORKER_STEAL_DELTA: &str = "tokio_worker_steal_delta";
/// Per-worker local-queue overflow-to-global delta over the sample interval, labelled by `worker`
/// (gauge).
pub const TOKIO_WORKER_OVERFLOW_DELTA: &str = "tokio_worker_overflow_delta";
/// Per-worker local run-queue depth, labelled by `worker` (gauge).
pub const TOKIO_WORKER_LOCAL_QUEUE_DEPTH: &str = "tokio_worker_local_queue_depth";
/// Per-worker mean poll duration, labelled by `worker` (gauge, microseconds).
pub const TOKIO_WORKER_MEAN_POLL_TIME_US: &str = "tokio_worker_mean_poll_time_us";
/// Threads in the blocking pool (gauge).
pub const TOKIO_BLOCKING_THREADS: &str = "tokio_blocking_threads";
/// Idle threads in the blocking pool (gauge).
pub const TOKIO_IDLE_BLOCKING_THREADS: &str = "tokio_idle_blocking_threads";
/// Tasks waiting for a blocking thread (gauge).
pub const TOKIO_BLOCKING_QUEUE_DEPTH: &str = "tokio_blocking_queue_depth";

/// Cohort bytecode invoked a symbol with no registered native (counter). The function name is
/// logged, not labelled, to keep cardinality bounded.
pub const STAGE1_HOGVM_UNKNOWN_FUNCTION: &str = "stage1_hogvm_unknown_function_total";
/// Any other VM/program failure during cohort evaluation, coerced to `false`, labelled by `reason`
/// (a bounded semantic bucket: `type_coercion`|`stack`|`program`|`runtime`|… — see
/// `vm_error_reason`) (counter).
pub const STAGE1_HOGVM_ERROR: &str = "stage1_hogvm_error_total";
/// `properties`/`person_properties` JSON parse failure, labelled by `field` (counter).
pub const STAGE1_GLOBALS_PARSE_ERROR: &str = "stage1_globals_parse_error_total";

/// Partitions with a live worker channel registered on the router (gauge).
pub const PARTITIONS_ACTIVE: &str = "partitions_active";
/// Messages dropped while routing (no live worker), labelled by `reason` (counter).
pub const PARTITION_ROUTE_DROPPED_TOTAL: &str = "partition_route_dropped_total";
/// Sub-batches queued in a partition worker's channel, labelled by `partition` (gauge).
pub const PARTITION_CHANNEL_DEPTH: &str = "partition_channel_depth";
/// Events held back because a partition worker's channel was full, labelled by `partition` (counter).
/// Backpressure, not loss: the partition is paused and its events redispatch once the channel drains.
/// Re-counted on every retry of a still-full holdover, so it is a pressure rate, not a distinct-event
/// count.
pub const PARTITION_CHANNEL_FULL_TOTAL: &str = "partition_channel_full_total";
/// Un-drained events in a partition worker's channel (plus the batch it is processing), labelled by
/// `partition` (gauge). A value pinned near `PARTITION_INTAKE_MAX_EVENTS` that never drains flags a
/// stuck worker.
pub const PARTITION_INTAKE_EVENTS: &str = "partition_intake_events";
/// Partitions currently paused on the events consumer to shed downstream backpressure (gauge).
pub const PARTITIONS_PAUSED: &str = "partitions_paused";
/// Events currently held across all paused partitions, awaiting redispatch (gauge). Bounded — a
/// paused partition stops fetching — so a climbing value flags a stuck worker.
pub const PENDING_HELD_EVENTS: &str = "pending_held_events";

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
/// Condition evaluations skipped because the result was already known, labelled by `reason`
/// (`event_name_gate`) (counter).
pub const STAGE1_CONDITIONS_SKIPPED: &str = "stage1_conditions_skipped_total";
/// Person side of an event resolved against the durable [`crate::stage1::PersonRecord`], labelled by
/// `result` (`fresh`|`stale_props`|`stale_catalog`|`stale_both`|`absent`|`corrupt`|`argmax_stale`|
/// `replay`) (counter). One increment per event that touches the person side. `absent`/`corrupt` come
/// from the prior-record classification (an evaluation from nothing), not the freshness axis, so they
/// are not folded into `stale_both`.
pub const STAGE1_PERSON_RECORD_TOTAL: &str = "stage1_person_record_total";
/// Encoded byte size of a [`crate::stage1::PersonRecord`] at each write (histogram). Watches record
/// growth on hot persons; the TTL backstop bounds it.
pub const STAGE1_PERSON_RECORD_SIZE_BYTES: &str = "stage1_person_record_size_bytes";
/// Behavioral applies staged per event — the write fan-out of the behavioral side (histogram).
pub const STAGE1_BEHAVIORAL_APPLIES: &str = "stage1_behavioral_applies";
/// Leaf membership flips emitted, labelled by `kind` (counter).
pub const STAGE1_TRANSITIONS: &str = "stage1_transitions_total";
/// `cf_behavioral` records written, labelled by `variant` (counter).
pub const STAGE1_STATE_WRITES: &str = "stage1_state_writes_total";
/// Applies skipped because the source `(partition, offset)` was already folded in, labelled by
/// `variant` (counter).
pub const STAGE1_REPLAY_SKIPPED: &str = "stage1_replay_skipped_total";
/// Applies skipped because the leaf's resolved variant is unsupported, labelled by `variant`
/// (counter). A defensive guard against a stale catalog.
pub const STAGE1_UNSUPPORTED_VARIANT_SKIPPED: &str = "stage1_unsupported_variant_skipped_total";
/// Stored `cf_behavioral` values that failed to decode; the key is skipped, not panicked (counter).
pub const STAGE1_STATE_DECODE_ERROR: &str = "stage1_state_decode_error_total";
/// End-to-end per-event processing latency in the worker (histogram, seconds).
pub const STAGE1_EVENT_PROCESS_DURATION: &str = "stage1_event_process_duration_seconds";
/// Keys in the event's single batched Stage-1 pre-read — the reads-per-event distribution
/// (histogram).
pub const STAGE1_SNAPSHOT_KEYS: &str = "stage1_snapshot_keys";

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
/// `cohort_cascade_events` envelopes consumed and successfully decoded (counter).
pub const COHORT_STREAM_CASCADES_CONSUMED: &str = "cohort_stream_cascades_consumed_total";
/// `cohort_cascade_events` payloads that were empty or failed to decode (counter).
pub const COHORT_STREAM_CASCADE_DESERIALIZE_ERRORS: &str =
    "cohort_stream_cascade_deserialize_errors_total";
/// Cascade messages dropped because the partition is no longer owned or shutdown is draining
/// (counter).
pub const COHORT_STREAM_CASCADES_SKIPPED_NOT_OWNED: &str =
    "cohort_stream_cascades_skipped_not_owned_total";
/// Decoded `KAFKA_PERSON_MERGE_EVENTS` envelopes accumulated per consume → dispatch cycle
/// (histogram). A separate constant per topic, not a label.
pub const COHORT_STREAM_MERGES_CONSUME_BATCH_SIZE: &str = "cohort_stream_merges_consume_batch_size";
/// Decoded `cohort_merge_state_transfer` envelopes accumulated per consume → dispatch cycle
/// (histogram).
pub const COHORT_STREAM_TRANSFERS_CONSUME_BATCH_SIZE: &str =
    "cohort_stream_transfers_consume_batch_size";
/// Decoded `cohort_cascade_events` envelopes accumulated per consume → dispatch cycle (histogram).
pub const COHORT_STREAM_CASCADES_CONSUME_BATCH_SIZE: &str =
    "cohort_stream_cascades_consume_batch_size";
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

/// Sweep cycles that fired, labelled by `loop`
/// (`eviction`|`redrive`|`merge_gc`|`checkpoint`|`store_stats`) (counter).
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
/// Behavioral rows enumerated for P_old on one merge drain — the drain-scan cost distribution
/// (histogram). Recorded once per non-replay drain. The drain enumerates P_old's leaves with a prefix
/// scan, so this is the visibility into how many rows that scan touches.
pub const MERGE_DRAIN_LEAVES_SCANNED: &str = "merge_drain_leaves_scanned";

/// Merge-CF keys scanned by the GC sweep, labelled by `cf` (counter).
pub const MERGE_GC_KEYS_SCANNED_TOTAL: &str = "merge_gc_keys_scanned_total";
/// Merge-CF keys the GC sweep deleted (expired or undecodable), labelled by `cf` (counter).
pub const MERGE_GC_KEYS_DELETED_TOTAL: &str = "merge_gc_keys_deleted_total";
/// Merge-CF values the GC sweep could not decode, labelled by `cf` (counter). Each is deleted and
/// folded into [`MERGE_GC_KEYS_DELETED_TOTAL`] (an unreadable timestamp can never age out).
pub const MERGE_GC_UNDECODABLE_TOTAL: &str = "merge_gc_undecodable_total";

/// `cf_stage2` rows scanned by the orphan GC pass (counter).
pub const STAGE2_ORPHAN_GC_KEYS_SCANNED_TOTAL: &str = "stage2_orphan_gc_keys_scanned_total";
/// `cf_stage2` orphan rows the pass deleted — the cohort left the composable set (counter).
pub const STAGE2_ORPHAN_GC_KEYS_DELETED_TOTAL: &str = "stage2_orphan_gc_keys_deleted_total";
/// Orphan-GC passes skipped without scanning, labelled by `reason`
/// (`catalog_not_loaded`|`empty_catalog`) (counter).
pub const STAGE2_ORPHAN_GC_SKIPPED_TOTAL: &str = "stage2_orphan_gc_skipped_total";
/// `cf_stage2` keys the orphan GC could not classify and left in place (counter): a key the decoder
/// rejected, or an id that overflows `i32`.
pub const STAGE2_ORPHAN_GC_UNDECODABLE_KEYS_TOTAL: &str = "stage2_orphan_gc_undecodable_keys_total";

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
        assert_eq!(CASCADE_DEPTH_OBSERVED, "cascade_depth_observed");
        assert_eq!(CASCADE_DEPTH_EXCEEDED_TOTAL, "cascade_depth_exceeded_total");
        assert_eq!(
            CASCADE_CYCLE_DETECTED_RUNTIME_TOTAL,
            "cascade_cycle_detected_runtime_total",
        );
        assert_eq!(CASCADE_FANOUT_CAPPED_TOTAL, "cascade_fanout_capped_total");
    }

    #[test]
    fn durability_metric_names_are_stable() {
        assert_eq!(CHECKPOINT_DURATION_SECONDS, "checkpoint_duration_seconds");
        assert_eq!(CHECKPOINT_SIZE_BYTES, "checkpoint_size_bytes");
        assert_eq!(CHECKPOINT_FILE_COUNT, "checkpoint_file_count");
        assert_eq!(CHECKPOINT_UPLOADS_TOTAL, "checkpoint_uploads_total");
        assert_eq!(
            CHECKPOINT_UPLOAD_DURATION_SECONDS,
            "checkpoint_upload_duration_seconds",
        );
        assert_eq!(
            CHECKPOINT_FILES_UPLOADED_TOTAL,
            "checkpoint_files_uploaded_total",
        );
        assert_eq!(
            CHECKPOINT_FILES_DOWNLOADED_TOTAL,
            "checkpoint_files_downloaded_total",
        );
        assert_eq!(CHECKPOINT_PLAN_FILES_TOTAL, "checkpoint_plan_files_total");
        assert_eq!(
            CHECKPOINT_FILE_FETCH_DURATION_SECONDS,
            "checkpoint_file_fetch_duration_seconds",
        );
        assert_eq!(
            CHECKPOINT_FILES_FETCH_DURATION_SECONDS,
            "checkpoint_files_fetch_duration_seconds",
        );
        assert_eq!(
            CHECKPOINT_FILE_FETCH_STORE_DURATION_SECONDS,
            "checkpoint_file_fetch_store_duration_seconds",
        );
        assert_eq!(
            CHECKPOINT_LIST_DURATION_SECONDS,
            "checkpoint_list_duration_seconds",
        );
        assert_eq!(CHECKPOINT_RESTORE_TOTAL, "checkpoint_restore_total");
        assert_eq!(
            CHECKPOINT_RESTORE_DURATION_SECONDS,
            "checkpoint_restore_duration_seconds",
        );
        assert_eq!(
            CHECKPOINT_IMPORT_DURATION_SECONDS,
            "checkpoint_import_duration_seconds",
        );
        assert_eq!(
            CHECKPOINT_IMPORT_ATTEMPT_DURATION_SECONDS,
            "checkpoint_import_attempt_duration_seconds",
        );
        assert_eq!(
            DURABLE_RESTORE_PENDING_TRANSFERS_RECOVERED_PARTITIONS_TOTAL,
            "durable_restore_pending_transfers_recovered_partitions_total",
        );
    }

    #[test]
    fn store_and_tokio_observability_metric_names_are_stable() {
        // These names are a dashboard contract; a rename must be deliberate, not accidental. Every
        // new store/tokio constant is pinned so a rename cannot silently break a panel.
        assert_eq!(STORE_READ_DURATION_SECONDS, "store_read_duration_seconds");
        assert_eq!(STORE_READS_TOTAL, "store_reads_total");
        assert_eq!(
            STORE_OFFLOAD_PERMIT_WAIT_DURATION_SECONDS,
            "store_offload_permit_wait_duration_seconds",
        );
        assert_eq!(
            STORE_OFFLOAD_QUEUE_WAIT_DURATION_SECONDS,
            "store_offload_queue_wait_duration_seconds",
        );
        assert_eq!(
            STORE_OFFLOAD_EXEC_DURATION_SECONDS,
            "store_offload_exec_duration_seconds",
        );
        assert_eq!(STORE_OFFLOAD_INFLIGHT, "store_offload_inflight");
        assert_eq!(STORE_BLOCK_CACHE_HITS_TOTAL, "store_block_cache_hits_total");
        assert_eq!(
            STORE_BLOCK_CACHE_MISSES_TOTAL,
            "store_block_cache_misses_total"
        );
        assert_eq!(
            STORE_BLOCK_CACHE_DATA_HITS_TOTAL,
            "store_block_cache_data_hits_total",
        );
        assert_eq!(
            STORE_BLOCK_CACHE_DATA_MISSES_TOTAL,
            "store_block_cache_data_misses_total",
        );
        assert_eq!(
            STORE_BLOCK_CACHE_INDEX_HITS_TOTAL,
            "store_block_cache_index_hits_total",
        );
        assert_eq!(
            STORE_BLOCK_CACHE_INDEX_MISSES_TOTAL,
            "store_block_cache_index_misses_total",
        );
        assert_eq!(
            STORE_BLOCK_CACHE_FILTER_HITS_TOTAL,
            "store_block_cache_filter_hits_total",
        );
        assert_eq!(
            STORE_BLOCK_CACHE_FILTER_MISSES_TOTAL,
            "store_block_cache_filter_misses_total",
        );
        assert_eq!(
            STORE_BLOOM_FILTER_USEFUL_TOTAL,
            "store_bloom_filter_useful_total",
        );
        assert_eq!(
            STORE_BLOCK_CACHE_USAGE_BYTES,
            "store_block_cache_usage_bytes"
        );
        assert_eq!(STORE_SST_BYTES, "store_sst_bytes");
        assert_eq!(STORE_LIVE_DATA_BYTES, "store_live_data_bytes");
        assert_eq!(STORE_ESTIMATE_NUM_KEYS, "store_estimate_num_keys");
        assert_eq!(TOKIO_RUNTIME_BUSY_RATIO, "tokio_runtime_busy_ratio");
        assert_eq!(TOKIO_RUNTIME_ALIVE_TASKS, "tokio_runtime_alive_tasks");
        assert_eq!(
            TOKIO_RUNTIME_GLOBAL_QUEUE_DEPTH,
            "tokio_runtime_global_queue_depth",
        );
        assert_eq!(TOKIO_RUNTIME_NUM_WORKERS, "tokio_runtime_num_workers");
        assert_eq!(
            TOKIO_WORKER_BUSY_DURATION_DELTA,
            "tokio_worker_busy_duration_delta_secs",
        );
        assert_eq!(TOKIO_WORKER_PARK_DELTA, "tokio_worker_park_delta");
        assert_eq!(TOKIO_WORKER_POLL_DELTA, "tokio_worker_poll_delta");
        assert_eq!(TOKIO_WORKER_STEAL_DELTA, "tokio_worker_steal_delta");
        assert_eq!(TOKIO_WORKER_OVERFLOW_DELTA, "tokio_worker_overflow_delta");
        assert_eq!(
            TOKIO_WORKER_LOCAL_QUEUE_DEPTH,
            "tokio_worker_local_queue_depth",
        );
        assert_eq!(
            TOKIO_WORKER_MEAN_POLL_TIME_US,
            "tokio_worker_mean_poll_time_us",
        );
        assert_eq!(TOKIO_BLOCKING_THREADS, "tokio_blocking_threads");
        assert_eq!(TOKIO_IDLE_BLOCKING_THREADS, "tokio_idle_blocking_threads");
        assert_eq!(TOKIO_BLOCKING_QUEUE_DEPTH, "tokio_blocking_queue_depth");
    }

    #[test]
    fn partition_backpressure_metric_names_are_stable() {
        assert_eq!(PARTITION_CHANNEL_FULL_TOTAL, "partition_channel_full_total");
        assert_eq!(PARTITION_INTAKE_EVENTS, "partition_intake_events");
        assert_eq!(PARTITIONS_PAUSED, "partitions_paused");
        assert_eq!(PENDING_HELD_EVENTS, "pending_held_events");
    }

    #[test]
    fn person_record_metric_names_are_stable() {
        assert_eq!(STAGE1_PERSON_RECORD_TOTAL, "stage1_person_record_total");
        assert_eq!(
            STAGE1_PERSON_RECORD_SIZE_BYTES,
            "stage1_person_record_size_bytes",
        );
        assert_eq!(STAGE1_BEHAVIORAL_APPLIES, "stage1_behavioral_applies");
    }

    #[test]
    fn stage2_orphan_gc_metric_names_are_stable() {
        assert_eq!(
            STAGE2_ORPHAN_GC_KEYS_SCANNED_TOTAL,
            "stage2_orphan_gc_keys_scanned_total",
        );
        assert_eq!(
            STAGE2_ORPHAN_GC_KEYS_DELETED_TOTAL,
            "stage2_orphan_gc_keys_deleted_total",
        );
        assert_eq!(
            STAGE2_ORPHAN_GC_SKIPPED_TOTAL,
            "stage2_orphan_gc_skipped_total"
        );
        assert_eq!(
            STAGE2_ORPHAN_GC_UNDECODABLE_KEYS_TOTAL,
            "stage2_orphan_gc_undecodable_keys_total",
        );
    }

    #[test]
    fn schema_guard_and_drain_scan_metric_names_are_stable() {
        assert_eq!(
            STORE_SCHEMA_MISMATCH_WIPES_TOTAL,
            "store_schema_mismatch_wipes_total",
        );
        assert_eq!(MERGE_DRAIN_LEAVES_SCANNED, "merge_drain_leaves_scanned");
    }
}
