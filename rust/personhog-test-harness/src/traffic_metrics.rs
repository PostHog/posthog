//! Metrics for the continuous traffic mode.
//!
//! Only `traffic` installs the exporter; the bounded modes never call
//! [`serve`], so the `metrics::` macros sprinkled through shared code are
//! no-ops there. Violations are exported as counters by kind so a dev
//! alert can fire on any increment — the continuous mode's whole point is
//! that a consistency violation becomes a page-shaped signal rather than
//! a process exit code.

use std::error::Error as _;
use std::process;
use std::time::Duration;

use anyhow::Result;
use axum::routing::get;
use axum::Router;
use metrics::{counter, histogram};
use personhog_common::grpc::{code_as_str, NON_STATUS};
use personhog_common::metrics::WRITE_PATH_LATENCY_BUCKETS_MS;

use crate::report::ConsistencyViolation;

/// The harness's own traffic sources, kept separable because they fail
/// for different reasons: `blast` is the paced write load, `prober` the
/// read-your-write canary a live client would notice, and `verify` the
/// epoch close-out sweep whose failure means the epoch cannot be checked
/// at all rather than that a client was served badly.
pub const LANE_BLAST: &str = "blast";
pub const LANE_PROBER: &str = "prober";
pub const LANE_VERIFY: &str = "verify";

/// Metric label for a failed request. A status the server actually sent
/// arrives as a grpc-status trailer and keeps its code — a live server's
/// verdict. A status tonic synthesized from a dead connection (stream
/// reset, GOAWAY, broken transport) carries the transport error as its
/// `source`, and the code tonic picks for it is arbitrary — those become
/// "transport", so a killed connection can never masquerade as a
/// server-side cancel or timeout.
pub fn status_reason(err: &anyhow::Error) -> &'static str {
    match err.downcast_ref::<tonic::Status>() {
        Some(status) if status.source().is_some() => "transport",
        Some(status) => code_as_str(status.code()),
        None => NON_STATUS,
    }
}

fn millis(elapsed: Duration) -> f64 {
    elapsed.as_secs_f64() * 1000.0
}

/// Record an acked write. `reason` carries `ok` rather than being
/// omitted so every series of this counter has the same label set.
pub fn record_write_ok(lane: &'static str, elapsed: Duration) {
    counter!(
        "personhog_traffic_writes_total",
        "lane" => lane,
        "outcome" => "ok",
        "reason" => "ok",
    )
    .increment(1);
    histogram!("personhog_traffic_write_duration_ms", "lane" => lane).record(millis(elapsed));
}

/// Record a write the stack refused or dropped. Latency is deliberately
/// not recorded: a timeout's duration is the deadline, not the stack's
/// service time, and mixing the two distorts the percentiles.
///
/// The reason is always the request's true outcome, shutdown or not: the
/// bed's own teardown completes in-flight requests rather than aborting
/// them, so anything failing during a roll is stack signal — exactly the
/// "deploys must not fail traffic" promise the bed exists to check.
pub fn record_write_failed(lane: &'static str, err: &anyhow::Error) {
    counter!(
        "personhog_traffic_writes_total",
        "lane" => lane,
        "outcome" => "failed",
        "reason" => status_reason(err),
    )
    .increment(1);
}

pub fn record_read_ok(lane: &'static str, elapsed: Duration) {
    counter!(
        "personhog_traffic_reads_total",
        "lane" => lane,
        "outcome" => "ok",
        "reason" => "ok",
    )
    .increment(1);
    histogram!("personhog_traffic_read_duration_ms", "lane" => lane).record(millis(elapsed));
}

/// Record a strong read that did not return the person. `reason` is a
/// gRPC code for a failed call, or `missing` when the read succeeded but
/// found nothing — a served empty answer is a different failure from an
/// unavailable one, and only the harness can tell them apart.
pub fn record_read_failed(lane: &'static str, reason: &'static str) {
    counter!(
        "personhog_traffic_reads_total",
        "lane" => lane,
        "outcome" => "failed",
        "reason" => reason,
    )
    .increment(1);
}

/// Serve liveness + Prometheus metrics; runs for the process lifetime.
pub fn spawn_server(port: u16) -> Result<()> {
    let router = Router::new().route("/_liveness", get(|| async { "ok" }));
    // Client-observed request latencies live in single-digit
    // milliseconds; the default ladder's 10 → 50 ms step blurs them and
    // pins interpolated quantiles to bucket edges.
    let router = common_metrics::setup_metrics_routes_with_overrides(
        router,
        &[
            (
                common_metrics::Matcher::Full("personhog_traffic_write_duration_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                common_metrics::Matcher::Full("personhog_traffic_read_duration_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            // Batched identity/lifecycle RPCs: one sample per batch call,
            // same ladder — their cost is a handful of round trips.
            (
                common_metrics::Matcher::Full("personhog_traffic_pool_seed_duration_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
            (
                common_metrics::Matcher::Full("personhog_traffic_pool_delete_duration_ms".into()),
                WRITE_PATH_LATENCY_BUCKETS_MS,
            ),
        ],
    );
    let bind = format!("0.0.0.0:{port}");
    tokio::spawn(async move {
        if let Err(e) = common_metrics::serve(router, &bind).await {
            // The exporter dying must not look like health: crash the
            // process so the deployment restarts it and the absence alarm
            // has something unambiguous to see.
            tracing::error!(error = %e, "metrics server failed");
            process::exit(1);
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
        counter!("personhog_traffic_violations_total", "kind" => kind).increment(1);
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
    use std::io::{Error as IoError, ErrorKind};

    use serde_json::{json, Value};
    use tonic::Status;

    use super::*;

    fn violation(key: &str) -> ConsistencyViolation {
        ConsistencyViolation {
            person_id: 1,
            key: key.to_string(),
            expected: json!("x"),
            actual: Value::Null,
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

    /// A status the server sent over the wire keeps its code; one tonic
    /// synthesized from a broken connection (it carries the transport
    /// error as its `source`) must report as "transport" — otherwise a
    /// killed connection is indistinguishable from a server-side cancel
    /// or timeout on the dashboards.
    #[test]
    fn status_reason_separates_wire_statuses_from_transport_failures() {
        let wire = anyhow::Error::new(Status::cancelled("server said stop"))
            .context("UpdatePersonProperties failed");
        assert_eq!(status_reason(&wire), "cancelled");

        let reset = IoError::new(ErrorKind::ConnectionReset, "peer reset");
        let synthesized = anyhow::Error::new(Status::from_error(Box::new(reset)))
            .context("UpdatePersonProperties failed");
        assert_eq!(status_reason(&synthesized), "transport");

        let not_a_status = anyhow::anyhow!("connect refused before any rpc");
        assert_eq!(status_reason(&not_a_status), NON_STATUS);
    }
}
