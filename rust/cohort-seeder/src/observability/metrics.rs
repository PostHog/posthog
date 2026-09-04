//! Observability leaf: the `seeder_*` metric-name constants (the seeder's metric manifest, which
//! dashboards depend on), the shared RAII duration timer, the bounded team label every per-team
//! series draws on, and the Prometheus recorder installer. Depends on the metrics crates plus the
//! allowlist type the team label reads its bound from; never on another seeder module.

use std::sync::Arc;
use std::time::{Duration, Instant};

use cohort_core::filters::TeamId;
use common_types::cohort::TeamAllowlist;
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
/// Pinned behavioral conditions by what a static read of their bytecode found, labelled by `class`
/// and `team_id` (counter). Counted once per run per unique condition hash, per stretch. Dark:
/// nothing reads the analysis yet, so this reports what real catalogs look like before anything is
/// built on it.
///
/// Read the class ratios, not the absolute totals: a restart re-counts every active run, and every
/// replica counts every run, because the once-per-run gate is process-local. The paired `info!` line
/// carries one run's exact numbers.
///
/// `team_id` names a team only while `REALTIME_COHORT_TEAM_ALLOWLIST` names few enough of them, and
/// collapses to `other` otherwise. It is here because the question these counters answer is about
/// one team's catalog; blended across teams they answer nobody's.
pub const CONDITIONS_CLASSIFIED: &str = "seeder_conditions_classified_total";
/// Conditions the static read could not narrow, labelled by a closed `reason`, the `op` that
/// stopped it (`none` when no opcode did), and `team_id` (counter). Counted on the same
/// once-per-run-per-stretch gate as [`CONDITIONS_CLASSIFIED`], and `team_id` collapses the same way.
///
/// Both label vocabularies are closed and never carry bytecode text: `reason` by construction, `op`
/// because it is one of `Operation`'s 57 variant names. The opcode is worth a dimension because one
/// fixable compiler template and a program nothing will ever narrow otherwise land in the same
/// `unsupported_op` bucket.
pub const CONDITIONS_UNANALYZABLE: &str = "seeder_conditions_unanalyzable_total";
/// Behavioral chunks by whether their scan narrowed, labelled by `outcome`
/// (`projected`/`full_columns`) and `team_id` (counter). One increment per scanned chunk.
///
/// `full_columns` is the fail-closed arm: at least one condition active on that chunk reads a whole
/// object or escaped the static analysis, so the scan selects every column. A team sitting at
/// `full_columns` is the signal to read the run's census for which event names block it.
pub const CHUNKS_PROJECTED: &str = "seeder_chunks_projected_total";
/// Shadow-compare verdicts per chunk, labelled by closed `result`
/// (`match`/`diff`/`error`/`no_rows`/`not_projected`) and `team_id` (counter). Emitted only while
/// `SEEDER_SCAN_SHADOW_COMPARE` is on, once per chunk that finishes its scan. A chunk cancelled by
/// shutdown or a lost lease increments nothing and runs again later.
///
/// `diff` is the validation failure signal — the paired `warn!` carries the chunk attribution and
/// exemplars. `error` means the diagnostic wide scan itself failed and the chunk's projected tiles
/// were emitted unverified.
///
/// The last two values are chunks no second query was issued for, because it could only have
/// agreed: `no_rows` where the authoritative scan read nothing, and `not_projected` where it was
/// already wide. Neither is evidence about projecting, so read compare coverage as `match` and
/// `diff` against their sum, not against the chunk count.
pub const SHADOW_COMPARE: &str = "seeder_shadow_compare_total";
/// Wall time of one chunk's diagnostic wide re-scan, including its fold and diff (histogram).
///
/// The compare arm runs after the authoritative scan on the same task, holding the chunk's worker
/// slot and lease, and [`CHUNK_SCAN_DURATION_SECONDS`] deliberately closes before it. Without this
/// series the arm's cost shows up only as slower chunk throughput, with nothing naming the cause —
/// which is the reading behind the decision to turn the knob off for the rest of a long reseed.
pub const SHADOW_COMPARE_DURATION_SECONDS: &str = "seeder_shadow_compare_duration_seconds";
/// Rows only the shadow compare's legacy wide arm refused to build globals for, labelled by
/// `team_id` (counter). Emitted only while `SEEDER_SCAN_SHADOW_COMPARE` is on, and at zero as well.
///
/// The difference between the two arms' skip counts, not the wide arm's total. A blob the
/// projection keeps whole or rebuilds from keys fails the same parse on both arms and explains no
/// divergence; only a blob the projection replaced with an empty literal is skipped on one side
/// and evaluated on the other. That difference is what separates a projection defect from the
/// over-count `sql::render_blob` documents, which lands in `result="diff"` indistinguishably.
pub const SHADOW_COMPARE_LEGACY_SKIPPED: &str = "seeder_shadow_compare_legacy_skipped_total";
/// Top-level JSON keys a narrowed scan rebuilds one blob from, labelled by `blob`
/// (`properties`/`person_properties`) and `team_id` (histogram). Zero means the blob is not read at
/// all and the scan selects an empty literal for it.
///
/// A blob some condition needs whole takes no sample: there is no key count to report for it, and a
/// sentinel would be indistinguishable from a real reading. Those show up as decoded bytes that do
/// not fall — read this against `seeder_scan_decoded_bytes_total{kind="behavioral"}`.
pub const PROJECTION_KEYS: &str = "seeder_projection_keys";
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
/// One run's person planning pass, end to end: the ClickHouse boundaries scan plus the Postgres
/// `plan_person_chunks` insert. Two databases under one timer, so a slow reading names neither on
/// its own — read it with `seeder_scan_received_bytes_total{kind="person_boundaries"}` to tell a
/// heavy scan from a slow insert.
pub const PERSON_PLANNING_DURATION_SECONDS: &str = "seeder_person_planning_duration_seconds";
/// Deliberately its own metric rather than [`CHUNK_SCAN_DURATION_SECONDS`] under a `kind` label:
/// the person path interleaves scan, evaluation, and paced enqueue into one inseparable loop, so
/// this spans all three, where the behavioral metric times the ClickHouse scan alone and accounts
/// delivery separately. One name across both would compare unlike spans.
pub const PERSON_CHUNK_SCAN_DURATION_SECONDS: &str = "seeder_person_chunk_scan_duration_seconds";

/// How many teams a per-team series names individually before it stops naming any.
///
/// Sized well above the shadow rollout's team count, so the collapse is a ceiling rather than a
/// routine truncation.
const MAX_LABELLED_TEAMS: usize = 32;

/// The label every team shares once a per-team series stops naming them.
const UNLABELLED_TEAM: &str = "other";

/// The team a metric belongs to, as a label value.
///
/// A team gets its own series only while `REALTIME_COHORT_TEAM_ALLOWLIST` names few enough of them.
/// The allowlist does not bound this on its own: it accepts `all` (which a set-but-empty variable
/// also parses to) and ranges of up to 100,000 ids, and the recorder never evicts a series, so a
/// wide rollout would retain one per team that ever seeded. The label exists because these series
/// answer questions about one team's catalog and scans, which a blended counter cannot; the paired
/// log lines carry the exact team either way, so collapsing costs the dashboard, not the answer.
pub fn team_label(allowlist: &TeamAllowlist, team_id: TeamId) -> Arc<str> {
    match allowlist {
        TeamAllowlist::Only(ids) if ids.len() <= MAX_LABELLED_TEAMS => {
            Arc::from(team_id.0.to_string().as_str())
        }
        TeamAllowlist::Only(_) | TeamAllowlist::All => Arc::from(UNLABELLED_TEAM),
    }
}

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

/// Bucket ladder for the two ClickHouse-bound chunk scan spans. The top bucket is
/// `SEEDER_CH_MAX_EXECUTION_TIME_SECS`, because a scan cannot outlive the server-side
/// execution-time budget: a chunk that reaches the last bucket was killed by ClickHouse. The value
/// is repeated here rather than read from `Config` so this module stays a leaf that no other seeder
/// module can pull a dependency through; a test binds it back to the config default. That binding
/// covers the default only, so a deployment that raises the budget by environment leaves this
/// ladder short and the last bucket stops meaning "killed".
const SCAN_DURATION_SECONDS_BUCKETS: &[f64] = &[
    1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, 7200.0, 14400.0,
];

/// Bucket ladder for [`PERSON_PLANNING_DURATION_SECONDS`], which spans two databases: the
/// ClickHouse boundaries scan and the Postgres `plan_person_chunks` insert. ClickHouse's
/// execution-time budget governs only the first, so the top bucket is not the scan ceiling — an
/// operator reading `+Inf` here must be able to suspect either database. The floor is milliseconds
/// because a small team's planning finishes well inside a second, and the scan ladder's 1.0s floor
/// erased that whole range.
const PERSON_PLANNING_SECONDS_BUCKETS: &[f64] = &[
    0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 15.0, 60.0, 300.0, 900.0, 1800.0, 3600.0, 14400.0,
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

/// Bucket ladder for [`PROJECTION_KEYS`], which counts JSON keys rather than seconds. The floor is
/// 0 because "this blob is not read at all" is the reading that matters most, and the seconds ladder
/// has no bucket that separates it from one key. The top is well above any condition set a person
/// writes by hand, so a run reaching it means the projection has stopped narrowing anything.
const PROJECTION_KEYS_BUCKETS: &[f64] = &[0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0];

/// Every seeder histogram that overrides the recorder-wide default, paired with its ladder. This is
/// the single source: [`configured_builder`] installs from it and the test iterates it, so a
/// histogram cannot be given a ladder in one place and checked against another. A histogram absent
/// from this table inherits [`DEFAULT_SECONDS_BUCKETS`], which is correct only if it measures a
/// short span in seconds.
const HISTOGRAM_LADDERS: &[(&str, &[f64])] = &[
    (PROJECTION_KEYS, PROJECTION_KEYS_BUCKETS),
    (CHUNK_SCAN_DURATION_SECONDS, SCAN_DURATION_SECONDS_BUCKETS),
    (
        SHADOW_COMPARE_DURATION_SECONDS,
        SCAN_DURATION_SECONDS_BUCKETS,
    ),
    (
        PERSON_CHUNK_SCAN_DURATION_SECONDS,
        SCAN_DURATION_SECONDS_BUCKETS,
    ),
    (
        PERSON_PLANNING_DURATION_SECONDS,
        PERSON_PLANNING_SECONDS_BUCKETS,
    ),
    (AGGREGATE_ENTRIES, AGGREGATE_ENTRIES_BUCKETS),
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
    let mut builder = PrometheusBuilder::new().set_buckets(DEFAULT_SECONDS_BUCKETS)?;
    for (name, ladder) in HISTOGRAM_LADDERS {
        builder = builder.set_buckets_for_metric(Matcher::Full((*name).to_owned()), ladder)?;
    }
    Ok(builder)
}

pub fn install_recorder() -> Result<PrometheusHandle, BuildError> {
    configured_builder()?.install_recorder()
}

#[cfg(test)]
mod tests {
    use std::collections::{HashMap, HashSet};

    use envconfig::Envconfig;
    use metrics::histogram;

    use super::*;

    /// The histograms that deliberately take no [`HISTOGRAM_LADDERS`] entry, because
    /// [`DEFAULT_SECONDS_BUCKETS`] already describes them. Listed so the test still proves they
    /// render as histograms rather than summaries.
    const DEFAULT_LADDER_HISTOGRAMS: &[&str] = &[
        PRODUCE_ACK_SECONDS,
        PACER_WAIT_SECONDS,
        RECONCILE_OBSERVATION_PASS_SECONDS,
    ];

    /// Renders one sample per histogram through the configured recorder.
    fn render_one_sample_each() -> String {
        let recorder = configured_builder()
            .expect("the configured bucket ladders are non-empty")
            .build_recorder();
        let handle = recorder.handle();
        metrics::with_local_recorder(&recorder, || {
            for (name, _) in HISTOGRAM_LADDERS {
                histogram!(*name).record(1.0);
            }
            for name in DEFAULT_LADDER_HISTOGRAMS {
                histogram!(*name).record(1.0);
            }
        });
        handle.render()
    }

    /// The exporter renders bucket bounds with `f64::to_string`, so an integral bound loses its
    /// fractional part: 14400.0 is `le="14400"`.
    fn top_bucket_label(ladder: &[f64]) -> String {
        ladder
            .last()
            .expect("every ladder has at least one bucket")
            .to_string()
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
        let expected = HISTOGRAM_LADDERS
            .iter()
            .map(|(name, ladder)| (*name, top_bucket_label(ladder)))
            .chain(
                DEFAULT_LADDER_HISTOGRAMS
                    .iter()
                    .map(|name| (*name, top_bucket_label(DEFAULT_SECONDS_BUCKETS))),
            );
        for (name, top_bucket) in expected {
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

    /// A blob no condition reads is the reading [`PROJECTION_KEYS`] exists to make visible, and it
    /// is only visible while the ladder has a bucket that holds nothing else. Drop the `0` bound and
    /// a chunk that read no keys and a chunk that read one both land in the first bucket, so the
    /// series stops answering "is this team still projecting?" while still rendering.
    #[test]
    fn the_projection_key_ladder_separates_zero_keys_from_one() {
        assert_eq!(
            PROJECTION_KEYS_BUCKETS.first(),
            Some(&0.0),
            "the ladder no longer starts at 0, so an unread blob shares a bucket with a read one"
        );
        let recorder = configured_builder()
            .expect("the configured bucket ladders are non-empty")
            .build_recorder();
        let handle = recorder.handle();
        metrics::with_local_recorder(&recorder, || {
            histogram!(PROJECTION_KEYS).record(0.0);
            histogram!(PROJECTION_KEYS).record(1.0);
        });
        let rendered = handle.render();
        assert!(
            rendered.contains(&format!("{PROJECTION_KEYS}_bucket{{le=\"0\"}} 1")),
            "the zero-key sample did not land alone in the le=0 bucket:\n{rendered}"
        );
    }

    /// The person planning timer spans a ClickHouse scan and a Postgres insert, so it must not
    /// share the scan ladder, whose 1.0s floor erases every sub-second planning pass. Two teams
    /// apart in size have to land in different buckets for the metric to say anything.
    #[test]
    fn person_planning_resolves_spans_below_the_scan_ladders_floor() {
        let floor = PERSON_PLANNING_SECONDS_BUCKETS[0];
        let scan_floor = SCAN_DURATION_SECONDS_BUCKETS[0];
        assert!(
            floor < scan_floor,
            "the planning ladder starts at {floor}, no finer than the scan ladder's {scan_floor}"
        );
        let sub_second = PERSON_PLANNING_SECONDS_BUCKETS
            .iter()
            .filter(|bound| **bound < 1.0)
            .count();
        assert!(
            sub_second >= 3,
            "only {sub_second} sub-second buckets; a fast planning pass has nowhere to land"
        );
    }

    /// The scan ladder's top bucket carries a claim — that a chunk reaching it was killed by
    /// ClickHouse — and that claim holds only while the bucket matches the execution-time budget.
    /// The ladder repeats the number rather than reading `Config`, so nothing but this ties the two
    /// together. A test module may import `Config` without the production module depending on it,
    /// which keeps `metrics` a leaf.
    #[test]
    fn the_scan_ladder_tops_out_at_the_clickhouse_execution_budget() {
        let config = crate::config::Config::init_from_hashmap(&HashMap::new())
            .expect("every seeder config field carries a default");
        assert_eq!(
            *SCAN_DURATION_SECONDS_BUCKETS
                .last()
                .expect("the scan ladder is non-empty"),
            config.seeder_ch_max_execution_time_secs as f64,
            "the scan ladder no longer tops out at the ClickHouse execution-time budget"
        );
    }

    /// An allowlist that can grow with the customer base must not mint a metric series per team.
    /// The recorder never evicts one, so a label that tracks team count leaks for the whole process
    /// lifetime — and `all`, which a set-but-empty variable also parses to, is the configuration
    /// the boundedness claim used to assume away.
    #[test]
    fn only_a_narrow_allowlist_names_teams_in_a_per_team_label() {
        let narrow = TeamAllowlist::Only(HashSet::from([2, 7]));
        assert_eq!(&*team_label(&narrow, TeamId(2)), "2");

        let wide = TeamAllowlist::Only((0..=MAX_LABELLED_TEAMS as i32).collect());
        assert_eq!(&*team_label(&wide, TeamId(2)), UNLABELLED_TEAM);
        assert_eq!(
            &*team_label(&TeamAllowlist::All, TeamId(2)),
            UNLABELLED_TEAM
        );
        assert_eq!(
            &*team_label(
                &"".parse::<TeamAllowlist>().expect("blank parses"),
                TeamId(2)
            ),
            UNLABELLED_TEAM
        );
    }
}
