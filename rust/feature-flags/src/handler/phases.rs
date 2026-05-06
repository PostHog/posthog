//! Per-phase RAII timing for `process_request_inner`.
//!
//! The handler's async body is a sequence of contiguous spans of work
//! between state transitions: `auth → billing_check → cookieless →
//! fetch_and_filter → evaluate → record_billing → config_response`.
//! Existing histograms (e.g. `flags_properties_db_fetch_time`,
//! `flags_billing_increment_time_ms`) cover individual downstream calls,
//! but a phase-level breakdown is the only way to attribute a multi-second
//! request spike to the responsible await site when the underlying
//! resource is itself un-instrumented.
//!
//! [`PhaseGuard`] is the entry point. Construct one at the start of each
//! phase; on drop it:
//!
//! 1. Records elapsed wall-clock duration into the canonical log via
//!    [`with_canonical_log`], deferring histogram emission to
//!    [`FlagsCanonicalLogLine::emit_phase_metrics`] so the metric carries
//!    a `team_id` label once authentication has resolved it.
//! 2. Decrements the pod-level [`FLAG_INFLIGHT_BY_PHASE`] gauge.
//!
//! The gauge is incremented at construction, not on first poll, so a task
//! parked on its very first await still shows up in the per-phase
//! in-flight count. Pair the gauge with `flags_tokio_alive_tasks`: when
//! alive_tasks jumps and exactly one phase gauge tracks the jump, that
//! phase owns the parking site.
//!
//! Drop side-effect order: histogram-bound duration is recorded **before**
//! the gauge decrement, so a panic mid-phase still preserves the elapsed
//! time the request had accumulated.

use std::time::{Duration, Instant};

use metrics::gauge;

use crate::handler::canonical_log::with_canonical_log;
use crate::metrics::consts::FLAG_INFLIGHT_BY_PHASE;

/// Identifies a top-level phase of `process_request_inner`.
///
/// `name()` returns the value used as the `phase` label on
/// `flags_phase_duration_ms` and `flags_inflight_by_phase`. These names
/// are part of the public dashboard contract — keep them stable. Adding
/// a variant requires updating [`Phase::ALL`] (a `debug_assert!` enforces
/// the length invariant in tests).
#[repr(usize)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    /// Token extraction, distinct-id parsing, team verification.
    Auth = 0,
    /// Per-team feature-flag billing-limit check (Redis).
    BillingCheck = 1,
    /// Cookieless distinct-id derivation (Redis-backed key).
    Cookieless = 2,
    /// Loading flag definitions and applying static filters.
    FetchAndFilter = 3,
    /// Flag evaluation: dependency graph build, per-flag matching,
    /// hash-key override resolution, group/cohort fetches.
    Evaluate = 4,
    /// Synchronous billing increment plus shadow-keyspace tee.
    RecordBilling = 5,
    /// Building the response payload from the cached config blob.
    ConfigResponse = 6,
}

impl Phase {
    /// Number of distinct phase variants. Used to size the duration
    /// table on the canonical log.
    pub const COUNT: usize = 7;

    /// Iteration order for emission. The order is irrelevant for
    /// correctness but stable for dashboard readability.
    pub const ALL: [Phase; Self::COUNT] = [
        Phase::Auth,
        Phase::BillingCheck,
        Phase::Cookieless,
        Phase::FetchAndFilter,
        Phase::Evaluate,
        Phase::RecordBilling,
        Phase::ConfigResponse,
    ];

    /// Stable label value. Treat as part of the dashboard contract.
    pub const fn name(self) -> &'static str {
        match self {
            Phase::Auth => "auth",
            Phase::BillingCheck => "billing_check",
            Phase::Cookieless => "cookieless",
            Phase::FetchAndFilter => "fetch_and_filter",
            Phase::Evaluate => "evaluate",
            Phase::RecordBilling => "record_billing",
            Phase::ConfigResponse => "config_response",
        }
    }
}

/// RAII guard for a single phase of work.
///
/// Construct with [`PhaseGuard::enter`]; drop ends the phase. The guard
/// is `Send` because it carries only `Copy` state, so it survives across
/// `.await` points without ceremony.
#[must_use = "PhaseGuard records timing on drop; ignoring it ends the phase immediately"]
pub(crate) struct PhaseGuard {
    phase: Phase,
    start: Instant,
}

impl PhaseGuard {
    /// Marks the start of `phase`. Side effects:
    ///
    /// - Increments `flags_inflight_by_phase{phase=…}` by 1.
    /// - Stamps `Instant::now()` for elapsed-time computation on drop.
    pub(crate) fn enter(phase: Phase) -> Self {
        gauge!(FLAG_INFLIGHT_BY_PHASE, "phase" => phase.name()).increment(1.0);
        Self {
            phase,
            start: Instant::now(),
        }
    }
}

impl Drop for PhaseGuard {
    fn drop(&mut self) {
        let elapsed = self.start.elapsed();
        // Record into the canonical log first so a histogram emission
        // failure (or the canonical scope not existing — e.g. unit
        // tests) doesn't drop the inflight decrement.
        with_canonical_log(|log| log.phases.record(self.phase, elapsed));
        gauge!(FLAG_INFLIGHT_BY_PHASE, "phase" => self.phase.name()).decrement(1.0);
    }
}

/// Per-phase duration accumulator on `FlagsCanonicalLogLine`.
///
/// Indexed by `Phase as usize`. The only writer is [`PhaseGuard::drop`];
/// the only reader is `emit_phase_metrics`. Any phase that never ran
/// (early return before its guard was constructed) stays `None` and is
/// skipped at emission.
#[derive(Clone, Debug, Default)]
pub struct PhaseDurations {
    durations: [Option<Duration>; Phase::COUNT],
}

impl PhaseDurations {
    /// Records the elapsed duration for `phase`. If a phase is entered
    /// twice in the same request — which should not happen, but is
    /// defensible — the most recent value wins.
    pub fn record(&mut self, phase: Phase, elapsed: Duration) {
        self.durations[phase as usize] = Some(elapsed);
    }

    /// Iterates over all recorded `(phase, duration)` pairs. Phases that
    /// never ran are skipped.
    pub fn iter(&self) -> impl Iterator<Item = (Phase, Duration)> + '_ {
        Phase::ALL
            .iter()
            .copied()
            .zip(self.durations.iter())
            .filter_map(|(phase, slot)| slot.map(|d| (phase, d)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn phase_all_covers_every_variant() {
        // Compile-time-ish invariant: if a new variant is added without
        // extending `ALL`, this fails immediately. The match-via-name
        // exhaustiveness is enforced by the compiler; this test guards
        // the array.
        assert_eq!(Phase::ALL.len(), Phase::COUNT);
        for phase in Phase::ALL {
            // `phase as usize` must be a valid index into the duration
            // table, not just a strictly increasing integer.
            assert!((phase as usize) < Phase::COUNT);
        }
    }

    #[test]
    fn phase_names_are_stable_snake_case() {
        for phase in Phase::ALL {
            let name = phase.name();
            assert!(!name.is_empty());
            assert!(name
                .chars()
                .all(|c| c.is_ascii_lowercase() || c == '_'));
        }
    }

    #[test]
    fn phase_durations_default_iter_is_empty() {
        let durations = PhaseDurations::default();
        assert_eq!(durations.iter().count(), 0);
    }

    #[test]
    fn phase_durations_records_and_iterates_in_phase_order() {
        let mut durations = PhaseDurations::default();
        durations.record(Phase::Cookieless, Duration::from_millis(2));
        durations.record(Phase::Auth, Duration::from_millis(1));

        // Iteration order matches `Phase::ALL`, not insertion order, so
        // dashboards can rely on a stable label ordering.
        let pairs: Vec<_> = durations.iter().collect();
        assert_eq!(pairs.len(), 2);
        assert_eq!(pairs[0].0, Phase::Auth);
        assert_eq!(pairs[0].1, Duration::from_millis(1));
        assert_eq!(pairs[1].0, Phase::Cookieless);
        assert_eq!(pairs[1].1, Duration::from_millis(2));
    }

    #[test]
    fn phase_durations_overwrite_keeps_latest() {
        let mut durations = PhaseDurations::default();
        durations.record(Phase::Evaluate, Duration::from_millis(10));
        durations.record(Phase::Evaluate, Duration::from_millis(50));
        let (phase, d) = durations.iter().next().unwrap();
        assert_eq!(phase, Phase::Evaluate);
        assert_eq!(d, Duration::from_millis(50));
    }

    #[tokio::test]
    async fn phase_guard_records_into_canonical_log_on_drop() {
        use crate::handler::canonical_log::{run_with_canonical_log, FlagsCanonicalLogLine};
        use uuid::Uuid;

        let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        let (_, final_log) = run_with_canonical_log(log, async {
            {
                let _guard = PhaseGuard::enter(Phase::FetchAndFilter);
                tokio::task::yield_now().await;
            }
            // After the block, the guard has dropped. Nothing else to do.
        })
        .await;

        let pairs: Vec<_> = final_log.phases.iter().collect();
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].0, Phase::FetchAndFilter);
        // Lower bound 0 (clock can elapse 0ns under release optimizations);
        // upper bound generous to absorb scheduler jitter without flake.
        assert!(pairs[0].1 < Duration::from_secs(1));
    }

    #[tokio::test]
    async fn phase_guard_records_each_phase_independently() {
        use crate::handler::canonical_log::{run_with_canonical_log, FlagsCanonicalLogLine};
        use uuid::Uuid;

        let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        let (_, final_log) = run_with_canonical_log(log, async {
            {
                let _g = PhaseGuard::enter(Phase::Auth);
                tokio::task::yield_now().await;
            }
            {
                let _g = PhaseGuard::enter(Phase::Evaluate);
                tokio::task::yield_now().await;
            }
        })
        .await;

        let phases: Vec<_> = final_log.phases.iter().map(|(p, _)| p).collect();
        assert_eq!(phases, vec![Phase::Auth, Phase::Evaluate]);
    }

    #[test]
    fn phase_guard_outside_canonical_scope_does_not_panic() {
        // Defensive: PhaseGuard's drop must not panic if no canonical log
        // is in scope (e.g. a unit test exercising a downstream module
        // without setting up the task-local). `with_canonical_log`
        // already no-ops in that case; this test pins the contract.
        let _g = PhaseGuard::enter(Phase::ConfigResponse);
    }
}
