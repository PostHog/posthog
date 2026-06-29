//! Prometheus recorder setup and the shuffler's metric-name constants.

use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

/// Every message that passed the gate parse, forwarded or not. The gate ignores most fields, so a
/// skipped event that is invalid only on an ignored field (e.g. missing `person_mode`) still counts.
pub const EVENTS_CONSUMED: &str = "shuffler_events_consumed_total";
pub const EVENTS_FORWARDED: &str = "shuffler_events_forwarded_total";
pub const EVENTS_DROPPED_NO_PERSON_ID: &str = "shuffler_events_dropped_no_person_id_total";
pub const EVENTS_SKIPPED_TEAM_GATE: &str = "shuffler_events_skipped_team_gate_total";
pub const PRODUCE_ERRORS: &str = "shuffler_produce_errors_total";
pub const ACTIVE_TEAMS: &str = "shuffler_active_teams";

/// # Panics
/// Panics if a global metrics recorder has already been installed.
pub fn install_recorder() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("failed to install Prometheus recorder")
}
