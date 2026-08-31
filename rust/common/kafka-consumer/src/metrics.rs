//! Every metric name this crate emits, in one place, pinned by a fixture
//! test so a new or renamed series is a reviewed diff. Every series carries
//! the `group` label (the consumer group id) so adopters stay distinguishable
//! on one dashboard; the librdkafka statistics series in `stats` are the
//! exception and stay unlabeled, see that module's docs.

/// Polls that accepted at least one message.
pub const POLLS_TOTAL: &str = "kafka_consumer_polls_total";
/// Messages accepted from polls.
pub const MESSAGES_POLLED_TOTAL: &str = "kafka_consumer_messages_polled_total";
/// Charge bytes accepted from polls (payload + key + headers).
pub const BYTES_POLLED_TOTAL: &str = "kafka_consumer_bytes_polled_total";
/// Uncommitted events currently charged against the budget.
pub const BUDGET_USED_EVENTS: &str = "kafka_consumer_budget_used_events";
/// Uncommitted bytes currently charged against the budget.
pub const BUDGET_USED_BYTES: &str = "kafka_consumer_budget_used_bytes";
/// 1 while the poll gate is closed (assignment paused), else 0.
pub const POLL_GATE_CLOSED: &str = "kafka_consumer_poll_gate_closed";
/// Gate transitions, labeled `to=closed|open`.
pub const POLL_GATE_TRANSITIONS_TOTAL: &str = "kafka_consumer_poll_gate_transitions_total";
/// Commit requests issued (one per batched issue, not per partition).
pub const COMMITS_ISSUED_TOTAL: &str = "kafka_consumer_commits_issued_total";
/// Partitions currently assigned, drains included.
pub const ASSIGNED_PARTITIONS: &str = "kafka_consumer_assigned_partitions";
/// Rebalance events, labeled `event=assign|revoke|lost|error`.
pub const REBALANCES_TOTAL: &str = "kafka_consumer_rebalances_total";
/// Seconds from a revoke to its hand-back; fetching is paused pod-wide for
/// this long.
pub const DRAIN_DURATION_SECONDS: &str = "kafka_consumer_drain_duration_seconds";
/// Stall watchdog firings (the loop exits after one).
pub const STALLS_TOTAL: &str = "kafka_consumer_stalls_total";
/// Non-fatal errors from `recv`.
pub const ERRORS_TOTAL: &str = "kafka_consumer_errors_total";
/// Commits the sentinel checked.
pub const COMMITS_CHECKED_TOTAL: &str = "kafka_consumer_commits_checked_total";
/// Sentinel violations, labeled `kind=backwards|repeat`.
pub const COMMIT_VIOLATIONS_TOTAL: &str = "kafka_consumer_commit_violations_total";
/// The offset last submitted for commit, per partition.
pub const COMMITTED_OFFSET: &str = "kafka_consumer_committed_offset";
/// The group's committed offset as the broker reports it, per partition.
pub const BROKER_COMMITTED_OFFSET: &str = "kafka_consumer_broker_committed_offset";
/// Attempted minus broker-confirmed, per partition.
pub const COMMIT_CONFIRMATION_LAG: &str = "kafka_consumer_commit_confirmation_lag";
/// Unix time of the last verified commit progress.
pub const LAST_SUCCESSFUL_COMMIT_TIMESTAMP_SECONDS: &str =
    "kafka_consumer_last_successful_commit_timestamp_seconds";
/// Commit monitor fetch failures.
pub const COMMIT_MONITOR_ERRORS_TOTAL: &str = "kafka_consumer_commit_monitor_errors_total";

/// The label every labeled series carries.
pub const GROUP_LABEL: &str = "group";

pub const ALL: &[&str] = &[
    POLLS_TOTAL,
    MESSAGES_POLLED_TOTAL,
    BYTES_POLLED_TOTAL,
    BUDGET_USED_EVENTS,
    BUDGET_USED_BYTES,
    POLL_GATE_CLOSED,
    POLL_GATE_TRANSITIONS_TOTAL,
    COMMITS_ISSUED_TOTAL,
    ASSIGNED_PARTITIONS,
    REBALANCES_TOTAL,
    DRAIN_DURATION_SECONDS,
    STALLS_TOTAL,
    ERRORS_TOTAL,
    COMMITS_CHECKED_TOTAL,
    COMMIT_VIOLATIONS_TOTAL,
    COMMITTED_OFFSET,
    BROKER_COMMITTED_OFFSET,
    COMMIT_CONFIRMATION_LAG,
    LAST_SUCCESSFUL_COMMIT_TIMESTAMP_SECONDS,
    COMMIT_MONITOR_ERRORS_TOTAL,
];

#[cfg(test)]
mod tests {
    use super::*;

    /// The fixture: change this list only with a dashboard change in hand.
    const FIXTURE: &str = "\
kafka_consumer_polls_total
kafka_consumer_messages_polled_total
kafka_consumer_bytes_polled_total
kafka_consumer_budget_used_events
kafka_consumer_budget_used_bytes
kafka_consumer_poll_gate_closed
kafka_consumer_poll_gate_transitions_total
kafka_consumer_commits_issued_total
kafka_consumer_assigned_partitions
kafka_consumer_rebalances_total
kafka_consumer_drain_duration_seconds
kafka_consumer_stalls_total
kafka_consumer_errors_total
kafka_consumer_commits_checked_total
kafka_consumer_commit_violations_total
kafka_consumer_committed_offset
kafka_consumer_broker_committed_offset
kafka_consumer_commit_confirmation_lag
kafka_consumer_last_successful_commit_timestamp_seconds
kafka_consumer_commit_monitor_errors_total
";

    /// The unlabeled librdkafka statistics series, see `stats`.
    const STATS_FIXTURE: &str = "\
kafka_consumer_fetchq_messages
kafka_consumer_fetchq_bytes
kafka_consumer_replyq_ops
kafka_consumer_broker_rtt_max_seconds
kafka_consumer_broker_outbuf_requests
kafka_consumer_broker_waitresp_requests
kafka_consumer_rebalance_total
kafka_consumer_fetchq_bytes_limit
kafka_consumer_fetchq_messages_limit
kafka_consumer_poll_messages_limit
kafka_consumer_poll_bytes_limit
";

    #[test]
    fn metric_names_match_the_fixture() {
        let expected: Vec<&str> = FIXTURE.lines().collect();
        assert_eq!(ALL, expected.as_slice());
        let expected: Vec<&str> = STATS_FIXTURE.lines().collect();
        assert_eq!(crate::stats::NAMES, expected.as_slice());
    }

    #[test]
    fn every_name_carries_the_crate_prefix() {
        for name in ALL.iter().chain(crate::stats::NAMES) {
            assert!(
                name.starts_with("kafka_consumer_"),
                "{name} is outside the crate's prefix"
            );
        }
    }
}
