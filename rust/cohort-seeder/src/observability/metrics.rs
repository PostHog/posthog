//! Observability leaf: the `seeder_*` metric-name constants (the seeder's metric manifest, which
//! dashboards depend on) and the Prometheus recorder installer. Depends on the metrics exporter only.

use metrics_exporter_prometheus::{BuildError, PrometheusBuilder, PrometheusHandle};

pub const RUNS_DISCOVERED: &str = "seeder_runs_discovered_total";
pub const BOUNDARY_ESTABLISHED: &str = "seeder_boundary_established_total";
pub const BOUNDARY_CAS_LOST: &str = "seeder_boundary_cas_lost_total";
pub const RUNS_WAITING_BOUNDARY: &str = "seeder_runs_waiting_boundary";
pub const RUN_VALIDATION_FAILURES: &str = "seeder_run_validation_failures_total";
pub const TZ_FALLBACK: &str = "seeder_tz_fallback_total";
pub const CONDITIONS_DROPPED: &str = "seeder_conditions_dropped_total";
pub const LOOKBACK_TRUNCATED: &str = "seeder_lookback_truncated_total";
pub const CHUNKS_PLANNED: &str = "seeder_chunks_planned_total";
pub const CHUNKS_CLAIMED: &str = "seeder_chunks_claimed_total";
pub const CHUNKS_RECLAIMED: &str = "seeder_chunks_reclaimed_total";
pub const CHUNKS_CONFIRMED: &str = "seeder_chunks_confirmed_total";
pub const CHUNKS_VACUOUS: &str = "seeder_chunks_vacuous_total";
pub const CHUNKS_FAILED: &str = "seeder_chunks_failed_total";
pub const CHUNKS_POISONED: &str = "seeder_chunks_poisoned_total";
pub const CHUNK_SCAN_DURATION_SECONDS: &str = "seeder_chunk_scan_duration_seconds";
pub const ROWS_SCANNED: &str = "seeder_rows_scanned_total";
pub const EVENTS_SKIPPED: &str = "seeder_events_skipped_total";
pub const CONDITIONS_EVALUATED: &str = "seeder_conditions_evaluated_total";
pub const HOGVM_ERRORS: &str = "seeder_hogvm_errors_total";
pub const AGGREGATE_ENTRIES: &str = "seeder_aggregate_entries";
pub const TILES_PRODUCED: &str = "seeder_tiles_produced_total";
pub const TILE_PRODUCE_QUEUE_FULL: &str = "seeder_tile_produce_queue_full_total";
pub const TILE_PRODUCE_ERRORS: &str = "seeder_tile_produce_errors_total";
pub const PRODUCE_ACK_SECONDS: &str = "seeder_produce_ack_seconds";
pub const PACER_WAIT_SECONDS: &str = "seeder_pacer_wait_seconds";
pub const LEASE_HEARTBEATS: &str = "seeder_lease_heartbeats_total";
pub const LEASE_LOST: &str = "seeder_lease_lost_total";
pub const RUN_CHUNKS_REMAINING: &str = "seeder_run_chunks_remaining";
pub const RUNS_WITHOUT_CHUNKS: &str = "seeder_runs_without_chunks";
pub const WINDOW_DAYS_MISMATCH: &str = "seeder_window_days_mismatch_total";
pub const RUNS_PLANNING_STAMPED: &str = "seeder_runs_planning_stamped_total";
pub const RUNS_PLANNING_WITHHELD: &str = "seeder_runs_planning_withheld_total";
pub const RECONCILE_DISPATCHES: &str = "seeder_reconcile_dispatches_total";
pub const RECONCILE_CAS_LOST: &str = "seeder_reconcile_cas_lost_total";
pub const RECONCILE_RECORD_INVALID: &str = "seeder_reconcile_record_invalid_total";
pub const RECONCILE_DISPATCHES_IN_FLIGHT: &str = "seeder_reconcile_dispatches_in_flight";
pub const RUNS_RECONCILING: &str = "seeder_runs_reconciling";
// Liveness, marker watcher, and observation.
pub const RECONCILE_MARKERS_OBSERVED: &str = "seeder_reconcile_markers_observed_total";
pub const RECONCILE_MARKER_PARSE_FAILURES: &str = "seeder_reconcile_marker_parse_failures_total";
pub const RECONCILE_MARKER_WATCH_LAG: &str = "seeder_reconcile_marker_watch_lag";
pub const RECONCILE_LIVENESS_LAGGING_PARTITIONS: &str =
    "seeder_reconcile_liveness_lagging_partitions";
pub const RECONCILE_COHORTS_COMPLETED: &str = "seeder_reconcile_cohorts_completed_total";
pub const RECONCILE_COHORTS_PARTIAL: &str = "seeder_reconcile_cohorts_partial_total";
pub const RECONCILE_COHORTS_SHORTFALL: &str = "seeder_reconcile_cohorts_shortfall_total";
pub const RECONCILE_ZERO_MARKER_RUNS: &str = "seeder_reconcile_zero_marker_runs_total";
pub const RUNS_OBSERVED: &str = "seeder_runs_observed_total";
pub const RECONCILE_WATCH_TRUNCATED: &str = "seeder_reconcile_watch_truncated_total";
pub const RECONCILE_OBSERVATION_STALLED_AGE_SECONDS: &str =
    "seeder_reconcile_observation_stalled_age_seconds";
pub const RECONCILE_OBSERVATION_PASS_SECONDS: &str = "seeder_reconcile_observation_pass_seconds";
pub const RECONCILE_OBSERVE_ERRORS: &str = "seeder_reconcile_observe_errors_total";
pub const RECONCILE_RUNS_UNDISPATCHED: &str = "seeder_reconcile_runs_undispatched";

pub fn install_recorder() -> Result<PrometheusHandle, BuildError> {
    PrometheusBuilder::new().install_recorder()
}
