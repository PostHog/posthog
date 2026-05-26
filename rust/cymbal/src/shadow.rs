//! Shadow lane: fires a fraction of processed batches at cymbal-server via
//! gRPC and compares a derived result signature built from the full output
//! properties payload for parity testing.
//!
//! The shadow task is fire-and-forget — the HTTP response is always
//! authoritative and the shadow result never affects it.

use std::{collections::HashMap, time::Instant};

use chrono::DateTime;
use cymbal_api::cymbal::v1::{
    cymbal_ingestion_client::CymbalIngestionClient, process_exception_batch_result::Outcome,
    BatchContext, ExceptionEvent, ProcessExceptionBatchRequest, ProcessingOptions,
};
use futures::StreamExt;
use prost_types::Timestamp;
use sha2::{Digest, Sha256};
use tonic::transport::Channel;
use tracing::warn;
use uuid::Uuid;

use crate::{
    metric_consts::{SHADOW_COMPARE_DURATION_SECONDS, SHADOW_COMPARE_TOTAL},
    types::event::AnyEvent,
};

pub struct ShadowClient {
    client: CymbalIngestionClient<Channel>,
}

impl ShadowClient {
    /// Connect to the cymbal-server gRPC endpoint at `addr` (host:port).
    pub async fn new(addr: &str) -> Result<Self, tonic::transport::Error> {
        let endpoint = format!("http://{addr}");
        let client = CymbalIngestionClient::connect(endpoint).await?;
        Ok(Self { client })
    }

    /// Send `events` to cymbal-server and compare a derived result signature
    /// against those produced by the old HTTP pipeline (`results`). The
    /// signature is built from the full output properties payload so parity
    /// checks can catch dropped or altered properties across the round trip.
    /// Errors are logged at WARN and never propagated.
    ///
    /// Only events whose old result is `Some` are included in the gRPC batch;
    /// suppressed events (null old result) are skipped.
    pub async fn compare(&self, events: Vec<AnyEvent>, results: Vec<Option<AnyEvent>>) {
        let started_at = Instant::now();

        // Build the (event_id → old result signature) map and the gRPC event list.
        let mut old_signatures: HashMap<String, Option<String>> = HashMap::new();
        let mut grpc_events: Vec<ExceptionEvent> = Vec::new();

        for (event, result) in events.iter().zip(results.iter()) {
            let Some(old_result) = result else { continue };

            let event_id = event.uuid.to_string();
            let old_signature = compute_result_signature_from_properties(&old_result.properties);
            old_signatures.insert(event_id.clone(), old_signature);

            let distinct_id = event
                .others
                .get("distinct_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            let properties_json = serde_json::to_vec(&event.properties).unwrap_or_default();

            grpc_events.push(ExceptionEvent {
                event_id,
                team_id: event.team_id as i64,
                distinct_id,
                timestamp: Some(parse_timestamp(&event.timestamp)),
                properties_json,
            });
        }

        if grpc_events.is_empty() {
            return;
        }

        let comparable_event_count = grpc_events.len() as u64;

        let request = ProcessExceptionBatchRequest {
            context: Some(BatchContext {
                batch_id: Uuid::now_v7().to_string(),
                metadata: HashMap::new(),
            }),
            events: grpc_events,
            options: Some(ProcessingOptions {
                skip_alerting: true,
                emit_internal_events: false,
                emit_signals: false,
            }),
        };

        // Clone the inner client so compare() can take &self.
        let mut client = self.client.clone();

        let stream = match client.process_exception_batch(request).await {
            Ok(response) => response.into_inner(),
            Err(e) => {
                metrics::counter!(SHADOW_COMPARE_TOTAL, "result" => "grpc_call_error")
                    .increment(comparable_event_count);
                warn!(
                    error = %e,
                    comparable_event_count,
                    duration_ms = started_at.elapsed().as_millis() as u64,
                    "Shadow gRPC call failed"
                );
                record_compare_duration(started_at);
                return;
            }
        };

        let mut stream = stream;
        while let Some(item) = stream.next().await {
            let result = match item {
                Ok(r) => r,
                Err(e) => {
                    metrics::counter!(SHADOW_COMPARE_TOTAL, "result" => "grpc_stream_error")
                        .increment(1);
                    warn!(
                        error = %e,
                        duration_ms = started_at.elapsed().as_millis() as u64,
                        "Shadow gRPC stream error"
                    );
                    continue;
                }
            };

            let event_id = &result.event_id;
            let old_signature = old_signatures
                .get(event_id)
                .and_then(|signature| signature.as_deref());

            let label = match result.outcome {
                Some(Outcome::Next(ref enriched)) => {
                    let new_signature = compute_result_signature(&enriched.properties_json);
                    let label = classify_signatures(old_signature, new_signature.as_deref());
                    if label == "signature_mismatch" {
                        warn!(
                            reason = label,
                            event_id = %event_id,
                            old_signature = ?old_signature,
                            new_signature = ?new_signature.as_deref(),
                            "Shadow result signature mismatch"
                        );
                    }
                    label
                }
                Some(Outcome::Drop(ref dropped)) => {
                    warn!(
                        reason = "shadow_drop",
                        event_id = %event_id,
                        old_signature = ?old_signature,
                        drop_reason = %dropped.reason,
                        "Shadow compare mismatch"
                    );
                    "shadow_drop"
                }
                Some(Outcome::Retry(ref retry)) => {
                    warn!(
                        reason = "shadow_retry",
                        event_id = %event_id,
                        old_signature = ?old_signature,
                        retry_reason = %retry.reason,
                        retry_after_ms = retry.retry_after_ms,
                        "Shadow compare mismatch"
                    );
                    "shadow_retry"
                }
                Some(Outcome::Error(ref error)) => {
                    warn!(
                        reason = "shadow_error",
                        event_id = %event_id,
                        old_signature = ?old_signature,
                        error_code = %error.code,
                        error_message = %error.message,
                        retryable = error.retryable,
                        "Shadow compare mismatch"
                    );
                    "shadow_error"
                }
                None => {
                    warn!(
                        reason = "shadow_missing",
                        event_id = %event_id,
                        old_signature = ?old_signature,
                        "Shadow compare returned no outcome"
                    );
                    "shadow_missing"
                }
            };

            metrics::counter!(SHADOW_COMPARE_TOTAL, "result" => label).increment(1);
        }

        record_compare_duration(started_at);
    }
}

fn record_compare_duration(started_at: Instant) {
    metrics::histogram!(SHADOW_COMPARE_DURATION_SECONDS).record(started_at.elapsed().as_secs_f64());
}

/// Returns `true` if this batch should be shadowed at the given sample rate.
///
/// `rate = 0.0` → never; `rate = 1.0` → always.
pub fn should_shadow(rate: f64) -> bool {
    rand::random::<f64>() < rate
}

/// Build a stable comparison signature from an output event payload.
///
/// The signature hashes the full output properties payload after recursively
/// sorting object keys so property order does not affect the result.
fn compute_result_signature(json: &[u8]) -> Option<String> {
    let v: serde_json::Value = serde_json::from_slice(json).ok()?;
    compute_result_signature_from_properties(&v)
}

fn compute_result_signature_from_properties(props: &serde_json::Value) -> Option<String> {
    let canonical = serde_json::to_vec(&canonicalize_json_value(props)).ok()?;
    let digest = Sha256::digest(canonical);
    Some(format!("{:x}", digest))
}

fn canonicalize_json_value(value: &serde_json::Value) -> serde_json::Value {
    match value {
        serde_json::Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort_unstable();

            let mut canonical = serde_json::Map::with_capacity(map.len());
            for key in keys {
                canonical.insert(key.clone(), canonicalize_json_value(&map[key]));
            }

            serde_json::Value::Object(canonical)
        }
        serde_json::Value::Array(items) => {
            serde_json::Value::Array(items.iter().map(canonicalize_json_value).collect())
        }
        _ => value.clone(),
    }
}

/// Parse an ISO-8601 / RFC-3339 timestamp string into a `prost_types::Timestamp`.
/// Falls back to the epoch on parse failure.
fn parse_timestamp(s: &str) -> Timestamp {
    // Try RFC 3339 first; some sources omit the trailing 'Z' offset.
    let parsed =
        DateTime::parse_from_rfc3339(s).or_else(|_| DateTime::parse_from_rfc3339(&format!("{s}Z")));

    match parsed {
        Ok(dt) => Timestamp {
            seconds: dt.timestamp(),
            nanos: dt.timestamp_subsec_nanos() as i32,
        },
        Err(_) => Timestamp::default(),
    }
}

/// Core parity classification: compare old and new fingerprints and return the
/// metric label.
fn classify_signatures(old: Option<&str>, new: Option<&str>) -> &'static str {
    match (old, new) {
        (Some(o), Some(n)) if o == n => "match",
        _ => "signature_mismatch",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn should_shadow_zero_rate_never_samples() {
        for _ in 0..100 {
            assert!(!should_shadow(0.0));
        }
    }

    #[test]
    fn should_shadow_full_rate_always_samples() {
        for _ in 0..100 {
            assert!(should_shadow(1.0));
        }
    }

    #[test]
    fn result_signature_includes_exception_fingerprint() {
        let left = br#"{"$exception_fingerprint":"abc123","$exception_issue_id":"11111111-1111-1111-1111-111111111111","$exception_handled":true}"#;
        let right = br#"{"$exception_fingerprint":"xyz789","$exception_issue_id":"11111111-1111-1111-1111-111111111111","$exception_handled":true}"#;

        let left_signature = compute_result_signature(left);
        let right_signature = compute_result_signature(right);

        assert_ne!(left_signature, right_signature);
    }

    #[test]
    fn result_signature_includes_additional_properties() {
        let left = br#"{"$exception_fingerprint":"abc123","custom":{"a":1},"extra":"present"}"#;
        let right = br#"{"$exception_fingerprint":"abc123","custom":{"a":1}}"#;

        let left_signature = compute_result_signature(left);
        let right_signature = compute_result_signature(right);

        assert_ne!(left_signature, right_signature);
    }

    #[test]
    fn result_signature_is_stable_across_object_key_order() {
        let left = br#"{"b":2,"nested":{"y":2,"x":1},"a":1}"#;
        let right = br#"{"a":1,"nested":{"x":1,"y":2},"b":2}"#;

        let left_signature = compute_result_signature(left);
        let right_signature = compute_result_signature(right);

        assert_eq!(left_signature, right_signature);
    }

    #[test]
    fn compare_reports_match_when_signatures_equal() {
        let label = classify_signatures(Some("sig-abc"), Some("sig-abc"));
        assert_eq!(label, "match");
    }

    #[test]
    fn compare_reports_mismatch_when_signatures_differ() {
        let label = classify_signatures(Some("sig-abc"), Some("sig-xyz"));
        assert_eq!(label, "signature_mismatch");
    }

    #[test]
    fn compare_reports_new_missing_when_new_is_none() {
        let label = classify_signatures(Some("sig-abc"), None);
        assert_eq!(label, "signature_mismatch");
    }

    #[test]
    fn compare_reports_old_missing_when_old_is_none() {
        let label = classify_signatures(None, Some("sig-abc"));
        assert_eq!(label, "signature_mismatch");
    }
}
