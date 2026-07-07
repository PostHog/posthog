//! Prometheus recorder setup and the shuffler's metric-name constants.

use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

// All labels are static — never per-partition (512-cardinality trap on the input topic).

/// Every message the pipeline received with a payload, forwardable or not (including
/// unparseable ones).
pub const EVENTS_CONSUMED: &str = "shuffler_events_consumed_total";
/// Increments on delivery ack: the event made it out.
pub const EVENTS_FORWARDED: &str = "shuffler_events_forwarded_total";
pub const EVENTS_DROPPED_NO_PERSON_ID: &str = "shuffler_events_dropped_no_person_id_total";
pub const EVENTS_SKIPPED_TEAM_GATE: &str = "shuffler_events_skipped_team_gate_total";
/// Serde failure at either gate or survivor parse; the event settles and is committed over.
pub const EVENTS_UNPARSEABLE: &str = "shuffler_events_unparseable_total";
/// Delivery failures + fatal enqueue errors.
pub const PRODUCE_ERRORS: &str = "shuffler_produce_errors_total";
pub const ACTIVE_TEAMS: &str = "shuffler_active_teams";

pub const FORWARDS_ENQUEUED: &str = "shuffler_forwards_enqueued_total";
/// Gauge, sampled at each commit tick.
pub const FORWARDS_INFLIGHT: &str = "shuffler_forwards_inflight";
/// Histogram, enqueue → delivery resolution; label `outcome` = `"acked"` | `"abandoned"`.
pub const PRODUCE_ACK_SECONDS: &str = "shuffler_produce_ack_seconds";
/// Forwards whose delivery failed after librdkafka's internal retries; dropped and committed over.
pub const EVENTS_ABANDONED: &str = "shuffler_events_abandoned_total";
pub const PRODUCE_QUEUE_FULL: &str = "shuffler_produce_queue_full_total";
pub const COMMITS: &str = "shuffler_commits_total";
pub const COMMIT_ERRORS: &str = "shuffler_commit_errors_total";
/// Gauge: observed-but-unconfirmed events across partitions ≈ the crash-replay window.
pub const UNCOMMITTED_EVENTS: &str = "shuffler_uncommitted_events";
pub const LEDGER_PARTITIONS: &str = "shuffler_ledger_partitions";

/// # Panics
/// Panics if a global metrics recorder has already been installed.
pub fn install_recorder() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("failed to install Prometheus recorder")
}
