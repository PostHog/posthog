//! Prometheus recorder setup and the shuffler's metric vocabulary.
//!
//! [`install_recorder`] installs the global recorder and returns the render handle consumed
//! by `GET /metrics`. The `*_METRIC` constants are the single source of truth for metric
//! names so the consumer, producer, and team-index emit consistent series (and so the
//! `/metrics` acceptance check has names to assert against).

use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

/// Events read from `clickhouse_events_json` (every consumed message, forwarded or not).
pub const EVENTS_CONSUMED: &str = "shuffler_events_consumed_total";
/// Envelopes successfully produced to `cohort_stream_events`.
pub const EVENTS_FORWARDED: &str = "shuffler_events_forwarded_total";
/// Events dropped because they carry no `person_id` (the routing key).
pub const EVENTS_DROPPED_NO_PERSON_ID: &str = "shuffler_events_dropped_no_person_id_total";
/// Events skipped because the team has zero realtime cohorts (the team gate).
pub const EVENTS_SKIPPED_TEAM_GATE: &str = "shuffler_events_skipped_team_gate_total";
/// Produce failures when publishing to `cohort_stream_events`.
pub const PRODUCE_ERRORS: &str = "shuffler_produce_errors_total";
/// Current number of teams with ≥1 realtime cohort (the team index size).
pub const ACTIVE_TEAMS: &str = "shuffler_active_teams";

/// Install the global Prometheus recorder. Call once at startup.
///
/// # Panics
/// Panics if a global metrics recorder has already been installed.
pub fn install_recorder() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("failed to install Prometheus recorder")
}
