//! Shadow lane: fires a fraction of processed batches at cymbal-server via
//! gRPC and compares `$exception_fingerprint` values for parity testing.
//!
//! The shadow task is fire-and-forget — the HTTP response is always
//! authoritative and the shadow result never affects it.

use std::collections::HashMap;

use chrono::DateTime;
use cymbal_api::cymbal::v1::{
    cymbal_ingestion_client::CymbalIngestionClient,
    process_exception_batch_result::Outcome,
    BatchContext, ExceptionEvent, ProcessExceptionBatchRequest, ProcessingOptions,
};
use futures::StreamExt;
use prost_types::Timestamp;
use tonic::transport::Channel;
use tracing::warn;
use uuid::Uuid;

use crate::{metric_consts::SHADOW_FINGERPRINT_MATCH, types::event::AnyEvent};

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

    /// Send `events` to cymbal-server and compare the resulting
    /// `$exception_fingerprint` values against those produced by the old HTTP
    /// pipeline (`results`). Errors are logged at WARN and never propagated.
    ///
    /// Only events whose old result is `Some` are included in the gRPC batch;
    /// suppressed events (null old result) are skipped.
    pub async fn compare(&self, events: Vec<AnyEvent>, results: Vec<Option<AnyEvent>>) {
        // Build (event_id → old_fingerprint) map and the gRPC event list.
        let mut old_fps: HashMap<String, Option<String>> = HashMap::new();
        let mut grpc_events: Vec<ExceptionEvent> = Vec::new();

        for (event, result) in events.iter().zip(results.iter()) {
            let Some(old_result) = result else { continue };

            let event_id = event.uuid.to_string();
            let old_fp = extract_fingerprint_from_properties(&old_result.properties);
            old_fps.insert(event_id.clone(), old_fp);

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
                warn!(error = %e, "Shadow gRPC call failed");
                return;
            }
        };

        let mut stream = stream;
        while let Some(item) = stream.next().await {
            let result = match item {
                Ok(r) => r,
                Err(e) => {
                    warn!(error = %e, "Shadow gRPC stream error");
                    continue;
                }
            };

            let event_id = &result.event_id;
            let old_fp = old_fps.get(event_id).and_then(|fp| fp.as_deref());

            let label = match result.outcome {
                Some(Outcome::Next(ref enriched)) => {
                    let new_fp = extract_fingerprint(&enriched.properties_json);
                    let label = classify_fingerprints(old_fp, new_fp.as_deref());
                    if label == "mismatch" {
                        warn!(
                            event_id = %event_id,
                            old_fingerprint = ?old_fp,
                            new_fingerprint = ?new_fp.as_deref(),
                            "Shadow fingerprint mismatch"
                        );
                    }
                    label
                }
                Some(Outcome::Drop(_))
                | Some(Outcome::Retry(_))
                | Some(Outcome::Error(_))
                | None => "new_missing",
            };

            metrics::counter!(SHADOW_FINGERPRINT_MATCH, "result" => label).increment(1);
        }
    }
}

/// Returns `true` if this batch should be shadowed at the given sample rate.
///
/// `rate = 0.0` → never; `rate = 1.0` → always.
pub fn should_shadow(rate: f64) -> bool {
    rand::random::<f64>() < rate
}

/// Extract `$exception_fingerprint` from a raw JSON byte slice.
fn extract_fingerprint(json: &[u8]) -> Option<String> {
    let v: serde_json::Value = serde_json::from_slice(json).ok()?;
    v.get("$exception_fingerprint")
        .and_then(|fp| fp.as_str())
        .map(|s| s.to_string())
}

/// Extract `$exception_fingerprint` from an `AnyEvent`'s properties value.
fn extract_fingerprint_from_properties(props: &serde_json::Value) -> Option<String> {
    props
        .get("$exception_fingerprint")
        .and_then(|fp| fp.as_str())
        .map(|s| s.to_string())
}

/// Parse an ISO-8601 / RFC-3339 timestamp string into a `prost_types::Timestamp`.
/// Falls back to the epoch on parse failure.
fn parse_timestamp(s: &str) -> Timestamp {
    // Try RFC 3339 first; some sources omit the trailing 'Z' offset.
    let parsed = DateTime::parse_from_rfc3339(s)
        .or_else(|_| DateTime::parse_from_rfc3339(&format!("{s}Z")));

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
fn classify_fingerprints(old: Option<&str>, new: Option<&str>) -> &'static str {
    match (old, new) {
        (Some(o), Some(n)) if o == n => "match",
        (Some(_), Some(_)) => "mismatch",
        (None, _) => "old_missing",
        (Some(_), None) => "new_missing",
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
    fn fingerprint_extracted_from_properties_json() {
        let json = br#"{"$exception_fingerprint":"abc123"}"#;
        let fp = extract_fingerprint(json);
        assert_eq!(fp.as_deref(), Some("abc123"));
    }

    #[test]
    fn compare_reports_match_when_fingerprints_equal() {
        // Tests the core comparison logic: same fingerprint → "match" label.
        let label = classify_fingerprints(Some("fp-abc"), Some("fp-abc"));
        assert_eq!(label, "match");
    }

    #[test]
    fn compare_reports_mismatch_when_fingerprints_differ() {
        let label = classify_fingerprints(Some("fp-abc"), Some("fp-xyz"));
        assert_eq!(label, "mismatch");
    }

    #[test]
    fn compare_reports_new_missing_when_new_is_none() {
        let label = classify_fingerprints(Some("fp-abc"), None);
        assert_eq!(label, "new_missing");
    }

    #[test]
    fn compare_reports_old_missing_when_old_is_none() {
        let label = classify_fingerprints(None, Some("fp-abc"));
        assert_eq!(label, "old_missing");
    }
}
