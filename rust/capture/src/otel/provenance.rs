use axum::http::HeaderMap;
use chrono::{DateTime, Utc};
use metrics::counter;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::gateway_provenance as shared;

use super::fan_out::SpanEvent;

const SIGNATURE_SCOPE: &str = "otel-v1";
const RELAY_PROPERTY: &str = "$ai_gateway_relay";
const PROVENANCE_METRIC: &str = "capture_ai_otel_gateway_provenance";
pub use crate::gateway_provenance::Provenance;

pub fn verify(
    headers: &HeaderMap,
    secret: Option<&str>,
    token: &str,
    content_type: &str,
    content_encoding: &str,
    body: &[u8],
    now: DateTime<Utc>,
) -> Provenance {
    let Some(secret) = secret.filter(|value| !value.is_empty()) else {
        return Provenance::Invalid;
    };
    let Some(signature) = shared::header_str(headers, shared::SIGNATURE_HEADER) else {
        return Provenance::Invalid;
    };
    let Some(signed_at) = shared::header_str(headers, shared::SIGNED_AT_HEADER) else {
        return Provenance::Invalid;
    };

    let body_digest = hex::encode(Sha256::digest(body));
    let message = shared::canonical(&[
        token,
        SIGNATURE_SCOPE,
        content_type,
        content_encoding,
        &body_digest,
        &signed_at,
    ]);
    shared::verify(secret.as_bytes(), &message, &signature, &signed_at, now)
}

pub fn apply(span_events: &mut [SpanEvent], provenance: Provenance) {
    let trusted = provenance == Provenance::Verified;
    let reason = match provenance {
        Provenance::Verified => "verified",
        Provenance::Stale => "stale",
        Provenance::Invalid => "invalid",
    };

    for span_event in span_events {
        let Some(properties) = span_event.properties.as_object_mut() else {
            continue;
        };
        properties.retain(|key, _| !key.starts_with(shared::GATEWAY_PREFIX));
        if trusted {
            properties.insert(shared::VERIFIED_PROPERTY.to_string(), Value::Bool(true));
            properties.insert(RELAY_PROPERTY.to_string(), Value::Bool(true));
        }
    }
    counter!(PROVENANCE_METRIC, "reason" => reason).increment(1);
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const SECRET: &str = "test-signing-secret";
    const TOKEN: &str = "phc_test";
    const SIGNED_AT: &str = "2026-07-16T12:34:56.12Z";
    const SIGNATURE: &str = "2253e5d860360f04d6532ec1b40fdd467ba9ce33a7be93b3fa612fa452bbd47a";
    const BODY: &[u8] = &[0x0a, 0x02, 0x01, 0x02];

    fn now() -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(SIGNED_AT)
            .unwrap()
            .with_timezone(&Utc)
    }

    fn signed_headers() -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(shared::SIGNATURE_HEADER, SIGNATURE.parse().unwrap());
        headers.insert(shared::SIGNED_AT_HEADER, SIGNED_AT.parse().unwrap());
        headers
    }

    #[test]
    fn accepts_gateway_known_answer_vector() {
        assert_eq!(
            verify(
                &signed_headers(),
                Some(SECRET),
                TOKEN,
                "application/x-protobuf",
                "gzip",
                BODY,
                now(),
            ),
            Provenance::Verified
        );
    }

    #[test]
    fn rejects_tampered_body() {
        assert_eq!(
            verify(
                &signed_headers(),
                Some(SECRET),
                TOKEN,
                "application/x-protobuf",
                "gzip",
                b"tampered",
                now(),
            ),
            Provenance::Invalid
        );
    }

    #[test]
    fn rejects_stale_signature() {
        assert_eq!(
            verify(
                &signed_headers(),
                Some(SECRET),
                TOKEN,
                "application/x-protobuf",
                "gzip",
                BODY,
                now() + chrono::Duration::seconds(shared::FRESHNESS_WINDOW_SECS + 1),
            ),
            Provenance::Stale
        );
    }

    #[test]
    fn strips_forged_properties_and_stamps_verified_batches() {
        let mut events = vec![SpanEvent {
            event_name: "$ai_span".to_string(),
            distinct_id: "user-1".to_string(),
            properties: json!({
                "$ai_gateway_verified": true,
                "$ai_gateway_request_id": "forged",
                "$ai_trace_id": "trace-1",
            }),
            timestamp: None,
        }];

        apply(&mut events, Provenance::Verified);

        let properties = events[0].properties.as_object().unwrap();
        assert_eq!(
            properties.get(shared::VERIFIED_PROPERTY),
            Some(&Value::Bool(true))
        );
        assert_eq!(properties.get(RELAY_PROPERTY), Some(&Value::Bool(true)));
        assert!(!properties.contains_key("$ai_gateway_request_id"));
        assert_eq!(properties.get("$ai_trace_id"), Some(&json!("trace-1")));
    }

    #[test]
    fn strips_forged_properties_from_unsigned_batches() {
        let mut events = vec![SpanEvent {
            event_name: "$ai_span".to_string(),
            distinct_id: "user-1".to_string(),
            properties: json!({"$ai_gateway_verified": true, "$ai_trace_id": "trace-1"}),
            timestamp: None,
        }];

        apply(&mut events, Provenance::Invalid);

        let properties = events[0].properties.as_object().unwrap();
        assert!(!properties.contains_key(shared::VERIFIED_PROPERTY));
        assert!(!properties.contains_key(RELAY_PROPERTY));
        assert_eq!(properties.get("$ai_trace_id"), Some(&json!("trace-1")));
    }
}
