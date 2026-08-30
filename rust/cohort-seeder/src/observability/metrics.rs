//! Observability leaf: the `seeder_*` metric-name constants (the seeder's metric manifest, which
//! dashboards depend on), the shared RAII duration timer, and the Prometheus recorder installer.
//! Depends on the metrics crates only.

use std::time::{Duration, Instant};

use metrics::histogram;
use metrics_exporter_prometheus::{BuildError, Matcher, PrometheusBuilder, PrometheusHandle};

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
/// Runs terminally failed because ≥1 chunk exhausted its retry budget, labelled by `kind`.
/// Such a run would otherwise park in `seeding` forever and hold its cohort's uniqueness slot,
/// blocking every future run for that cohort. The paired `warn!` carries the chunk and its error,
/// which is what an operator reads once this counter points them at a run.
pub const RUNS_FAILED_EXHAUSTED_CHUNKS: &str = "seeder_runs_failed_exhausted_chunks_total";
pub const CHUNK_SCAN_DURATION_SECONDS: &str = "seeder_chunk_scan_duration_seconds";
/// Compressed bytes a scan cursor read off the wire, labelled by `kind` (counter). Paired with
/// [`SCAN_DECODED_BYTES`], it tells a slow scan that moved a lot of data apart from one that moved
/// little and spent its time on CPU.
pub const SCAN_RECEIVED_BYTES: &str = "seeder_scan_received_bytes_total";
/// Decompressed bytes a scan cursor produced, labelled by `kind` (counter).
pub const SCAN_DECODED_BYTES: &str = "seeder_scan_decoded_bytes_total";
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
/// Reconcile dispatch attempts, labelled by bounded `outcome` and the run's `kind` (counter).
pub const RECONCILE_DISPATCHES: &str = "seeder_reconcile_dispatches_total";
/// Dispatch claims lost to a concurrent writer, labelled by the run's `kind` (counter).
pub const RECONCILE_CAS_LOST: &str = "seeder_reconcile_cas_lost_total";
/// Reconciling runs with no usable dispatch record, counted once per run per stretch and labelled by
/// `reason` (counter). A topic rename re-dispatches every in-flight run at once; the label keeps that
/// expected spike apart from a corrupt record.
pub const RECONCILE_RECORD_INVALID: &str = "seeder_reconcile_record_invalid_total";
pub const RECONCILE_DISPATCHES_IN_FLIGHT: &str = "seeder_reconcile_dispatches_in_flight";
/// Runs currently in the reconcile protocol, labelled by the run's `kind` (gauge). Published for
/// every discovered kind each tick, zeroes included, so a drained kind does not freeze.
pub const RUNS_RECONCILING: &str = "seeder_runs_reconciling";
// Liveness, marker watcher, and observation.
pub const RECONCILE_MARKERS_OBSERVED: &str = "seeder_reconcile_markers_observed_total";
/// Records the watcher rejected, labelled by `reason` (counter). On a dedicated marker topic every
/// record should be a marker, so any of these means something is mis-pointed or corrupt.
pub const RECONCILE_MARKER_PARSE_FAILURES: &str = "seeder_reconcile_marker_parse_failures_total";
pub const RECONCILE_MARKER_WATCH_LAG: &str = "seeder_reconcile_marker_watch_lag";
pub const RECONCILE_LIVENESS_LAGGING_PARTITIONS: &str =
    "seeder_reconcile_liveness_lagging_partitions";
/// Cohort participations settled complete, labelled by the run's `kind` (counter).
pub const RECONCILE_COHORTS_COMPLETED: &str = "seeder_reconcile_cohorts_completed_total";
/// Cohort participations terminally superseded while short, labelled by the run's `kind`
/// (counter).
pub const RECONCILE_COHORTS_PARTIAL: &str = "seeder_reconcile_cohorts_partial_total";
/// Cohort participations short of their markers with the pinned shape unchanged — the retryable
/// half of the split — labelled by the run's `kind` (counter).
pub const RECONCILE_COHORTS_SHORTFALL: &str = "seeder_reconcile_cohorts_shortfall_total";
/// Runs that settled without a single marker — the shape a processor that cannot decode the
/// tile's kind produces — labelled by the run's `kind` (counter).
pub const RECONCILE_ZERO_MARKER_RUNS: &str = "seeder_reconcile_zero_marker_runs_total";
/// Runs the observation pass settled, labelled by the run's `kind` (counter).
pub const RUNS_OBSERVED: &str = "seeder_runs_observed_total";
pub const RECONCILE_WATCH_TRUNCATED: &str = "seeder_reconcile_watch_truncated_total";
pub const RECONCILE_OBSERVATION_STALLED_AGE_SECONDS: &str =
    "seeder_reconcile_observation_stalled_age_seconds";
pub const RECONCILE_OBSERVATION_PASS_SECONDS: &str = "seeder_reconcile_observation_pass_seconds";
pub const RECONCILE_OBSERVE_ERRORS: &str = "seeder_reconcile_observe_errors_total";
/// Reconciling runs with no usable dispatch record, labelled by the run's `kind` (gauge).
/// Published for every discovered kind each tick, zeroes included, so a drained kind does not
/// freeze at its last reading.
pub const RECONCILE_RUNS_UNDISPATCHED: &str = "seeder_reconcile_runs_undispatched";
// Person-property seed path.
pub const PERSONS_SCANNED: &str = "seeder_persons_scanned_total";
pub const PERSON_SEEDS_PRODUCED: &str = "seeder_person_seeds_produced_total";
pub const PERSON_NONMATCHERS_SKIPPED: &str = "seeder_person_nonmatchers_skipped_total";
pub const PERSON_ROWS_SKIPPED: &str = "seeder_person_rows_skipped_total";
pub const PERSON_HOGVM_ERRORS: &str = "seeder_person_hogvm_errors_total";
pub const PERSON_BOUNDARIES_PLANNED: &str = "seeder_person_boundaries_planned_total";
pub const PERSON_PLANNING_DURATION_SECONDS: &str = "seeder_person_planning_duration_seconds";
/// Deliberately its own metric rather than [`CHUNK_SCAN_DURATION_SECONDS`] under a `kind` label:
/// the person path interleaves scan, evaluation, and paced enqueue into one inseparable loop, so
/// this spans all three, where the behavioral metric times the ClickHouse scan alone and accounts
/// delivery separately. One name across both would compare unlike spans.
pub const PERSON_CHUNK_SCAN_DURATION_SECONDS: &str = "seeder_person_chunk_scan_duration_seconds";

/// Records its lifetime into `metric` on drop, so every exit — early return, halt, cancellation —
/// is sampled without a recording site per path.
pub struct MetricTimer {
    metric: &'static str,
    started: Instant,
}

impl MetricTimer {
    pub fn start(metric: &'static str) -> Self {
        Self {
            metric,
            started: Instant::now(),
        }
    }

    pub fn elapsed(&self) -> Duration {
        self.started.elapsed()
    }
}

impl Drop for MetricTimer {
    fn drop(&mut self) {
        histogram!(self.metric).record(self.started.elapsed().as_secs_f64());
    }
}

/// Bucket ladder for every seeder histogram that measures a short wall-clock span in seconds:
/// [`PRODUCE_ACK_SECONDS`], [`PACER_WAIT_SECONDS`], and
/// [`RECONCILE_OBSERVATION_PASS_SECONDS`]. It is installed as the recorder-wide default, so a new
/// histogram inherits a real bucketed histogram instead of a rolling-window summary. A future
/// histogram measuring anything other than seconds needs its own
/// [`PrometheusBuilder::set_buckets_for_metric`] entry, or its samples land in the wrong ladder.
///
/// The recorder is process-wide, so this also shapes histograms from linked crates. The only one
/// the seeder reaches is `lifecycle`'s component shutdown duration, which is in seconds and well
/// inside the 60s top bucket; the shared `common-metrics` builder every other service installs
/// already renders it as a histogram too, on a millisecond ladder.
const DEFAULT_SECONDS_BUCKETS: &[f64] = &[
    0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0,
];

/// Bucket ladder for the three ClickHouse-bound scan spans. The top bucket is the default
/// `SEEDER_CH_MAX_EXECUTION_TIME_SECS` (14400), because a scan cannot outlive the server-side
/// execution-time budget: a chunk that reaches the last bucket was killed by ClickHouse. The value
/// is repeated here rather than read from `Config` so this module stays a leaf that no other seeder
/// module can pull a dependency through.
const SCAN_DURATION_SECONDS_BUCKETS: &[f64] = &[
    1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, 7200.0, 14400.0,
];

/// Bucket ladder for [`AGGREGATE_ENTRIES`], which counts `(person, condition)` pairs held in one
/// chunk's in-memory aggregate. It is a cardinality, not a duration, so it needs its own ladder;
/// the top bucket is the scale at which an operator should raise `SEEDER_BANDS_PER_DAY` to split
/// the day further.
const AGGREGATE_ENTRIES_BUCKETS: &[f64] = &[
    100.0,
    1_000.0,
    10_000.0,
    50_000.0,
    100_000.0,
    250_000.0,
    500_000.0,
    1_000_000.0,
    2_500_000.0,
    5_000_000.0,
    10_000_000.0,
];

/// The recorder configuration shared by [`install_recorder`] and its test.
///
/// Without `set_buckets` the exporter renders every histogram as a rolling-window summary, whose
/// quantiles read 0 once a rare long recording ages out of the window. That is exactly the shape of
/// the scan metrics, where one multi-hour chunk per hour is the signal.
///
/// The two `seeder_reconcile_*` lag and age metrics take no entry on purpose: they are gauges, and
/// a bucket ladder would not apply to them.
fn configured_builder() -> Result<PrometheusBuilder, BuildError> {
    PrometheusBuilder::new()
        .set_buckets(DEFAULT_SECONDS_BUCKETS)?
        .set_buckets_for_metric(
            Matcher::Full(CHUNK_SCAN_DURATION_SECONDS.to_owned()),
            SCAN_DURATION_SECONDS_BUCKETS,
        )?
        .set_buckets_for_metric(
            Matcher::Full(PERSON_CHUNK_SCAN_DURATION_SECONDS.to_owned()),
            SCAN_DURATION_SECONDS_BUCKETS,
        )?
        .set_buckets_for_metric(
            Matcher::Full(PERSON_PLANNING_DURATION_SECONDS.to_owned()),
            SCAN_DURATION_SECONDS_BUCKETS,
        )?
        .set_buckets_for_metric(
            Matcher::Full(AGGREGATE_ENTRIES.to_owned()),
            AGGREGATE_ENTRIES_BUCKETS,
        )
}

pub fn install_recorder() -> Result<PrometheusHandle, BuildError> {
    configured_builder()?.install_recorder()
}

#[cfg(test)]
mod tests {
    use metrics::histogram;

    use super::*;

    /// Every histogram the seeder records, paired with the top bucket its ladder must end on.
    const HISTOGRAM_LADDERS: [(&str, &str); 7] = [
        (CHUNK_SCAN_DURATION_SECONDS, "14400"),
        (PERSON_CHUNK_SCAN_DURATION_SECONDS, "14400"),
        (PERSON_PLANNING_DURATION_SECONDS, "14400"),
        (AGGREGATE_ENTRIES, "10000000"),
        (PRODUCE_ACK_SECONDS, "60"),
        (PACER_WAIT_SECONDS, "60"),
        (RECONCILE_OBSERVATION_PASS_SECONDS, "60"),
    ];

    /// Renders one sample per histogram through the configured recorder.
    fn render_one_sample_each() -> String {
        let recorder = configured_builder()
            .expect("the configured bucket ladders are non-empty")
            .build_recorder();
        let handle = recorder.handle();
        metrics::with_local_recorder(&recorder, || {
            for (name, _) in HISTOGRAM_LADDERS {
                histogram!(name).record(1.0);
            }
        });
        handle.render()
    }

    /// A histogram with no ladder renders as a summary, so its rare long recordings age out of the
    /// rolling window and its quantiles read 0. Asserting the exact top bucket of each ladder also
    /// pins that the per-metric overrides beat the recorder-wide default: the exporter's own
    /// `set_buckets_for_metric` documentation claims the opposite, while its implementation
    /// consults the overrides first. A dependency bump that makes the documentation true would
    /// collapse the scan metrics onto the 60s default ladder, and this test is what catches it.
    #[test]
    fn every_histogram_renders_with_its_own_bucket_ladder() {
        let rendered = render_one_sample_each();
        for (name, top_bucket) in HISTOGRAM_LADDERS {
            assert!(
                rendered.contains(&format!("{name}_bucket{{le=\"{top_bucket}\"}}")),
                "{name} is missing its le={top_bucket} bucket:\n{rendered}"
            );
            assert!(
                !rendered.contains(&format!("{name}{{quantile=")),
                "{name} rendered as a summary instead of a histogram:\n{rendered}"
            );
        }
    }
}
