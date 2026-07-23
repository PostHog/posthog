//! Metrics for the continuous traffic mode.
//!
//! Only `traffic` installs the exporter; the bounded modes never call
//! [`serve`], so the `metrics::` macros sprinkled through shared code are
//! no-ops there. Violations are exported as counters by kind so a dev
//! alert can fire on any increment — the continuous mode's whole point is
//! that a consistency violation becomes a page-shaped signal rather than
//! a process exit code.

use anyhow::Result;
use axum::routing::get;
use axum::Router;

use crate::report::ConsistencyViolation;

/// Serve liveness + Prometheus metrics; runs for the process lifetime.
pub fn spawn_server(port: u16) -> Result<()> {
    let router = Router::new().route("/_liveness", get(|| async { "ok" }));
    let router = common_metrics::setup_metrics_routes(router);
    let bind = format!("0.0.0.0:{port}");
    tokio::spawn(async move {
        if let Err(e) = common_metrics::serve(router, &bind).await {
            // The exporter dying must not look like health: crash the
            // process so the deployment restarts it and the absence alarm
            // has something unambiguous to see.
            tracing::error!(error = %e, "metrics server failed");
            std::process::exit(1);
        }
    });
    Ok(())
}

/// Stable metric label for a violation, derived from the journal's
/// violation key vocabulary. Property-key violations (an acked write
/// missing or mismatched on read-back) all classify as `missing_write`.
pub fn violation_kind(violation: &ConsistencyViolation) -> &'static str {
    match violation.key.as_str() {
        "__ack_version_duplicate" => "duplicate_version",
        "__strong_read_version" => "stale_read",
        "__version" => "pg_below_ack",
        "__row" | "__missing_person" => "missing_row",
        "__strong_read_failed" => "read_failed",
        "__ack_missing_person" => "ack_missing_person",
        _ => "missing_write",
    }
}

/// Record a batch of violations into the by-kind counter and log each one.
pub fn record_violations(epoch: u64, violations: &[ConsistencyViolation]) {
    for violation in violations {
        let kind = violation_kind(violation);
        metrics::counter!("personhog_traffic_violations_total", "kind" => kind).increment(1);
        tracing::error!(
            epoch,
            kind,
            person_id = violation.person_id,
            key = %violation.key,
            expected = %violation.expected,
            actual = %violation.actual,
            "consistency violation"
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn violation(key: &str) -> ConsistencyViolation {
        ConsistencyViolation {
            person_id: 1,
            key: key.to_string(),
            expected: serde_json::json!("x"),
            actual: serde_json::Value::Null,
        }
    }

    #[test]
    fn violation_kinds_cover_the_journal_vocabulary() {
        let cases = [
            ("__ack_version_duplicate", "duplicate_version"),
            ("__strong_read_version", "stale_read"),
            ("__version", "pg_below_ack"),
            ("__row", "missing_row"),
            ("__missing_person", "missing_row"),
            ("__strong_read_failed", "read_failed"),
            ("__ack_missing_person", "ack_missing_person"),
            ("harness_gate_3_17", "missing_write"),
        ];
        for (key, kind) in cases {
            assert_eq!(violation_kind(&violation(key)), kind, "{key}");
        }
    }
}
