use axum::http::HeaderMap;
use chrono::{DateTime, Duration, Utc};
use hmac::{Hmac, Mac};
use metrics::counter;
use serde_json::Value;
use sha2::{Digest, Sha256};

use super::fan_out::SpanEvent;

type HmacSha256 = Hmac<Sha256>;

const SIGNATURE_HEADER: &str = "PostHog-Ai-Gateway-Signature";
const SIGNED_AT_HEADER: &str = "PostHog-Ai-Gateway-Signed-At";
pub const TRACE_SIGNATURE_SCOPE: &str = "otel-v1";
pub const LOGS_SIGNATURE_SCOPE: &str = "otel-logs-v1";
const GATEWAY_PREFIX: &str = "$ai_gateway";
const VERIFIED_PROPERTY: &str = "$ai_gateway_verified";
const RELAY_PROPERTY: &str = "$ai_gateway_relay";
const PROVENANCE_METRIC: &str = "capture_ai_otel_gateway_provenance";
const FRESHNESS_WINDOW_SECS: i64 = 5 * 60;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provenance {
    Verified,
    Stale,
    Invalid,
}

pub struct SignedRequest<'a> {
    pub token: &'a str,
    pub content_type: &'a str,
    pub content_encoding: &'a str,
    pub body: &'a [u8],
    pub signature_scope: &'a str,
}

pub fn verify(
    headers: &HeaderMap,
    secret: Option<&str>,
    now: DateTime<Utc>,
    request: SignedRequest<'_>,
) -> Provenance {
    let Some(secret) = secret.filter(|value| !value.is_empty()) else {
        return Provenance::Invalid;
    };
    let Some(signature) = header_str(headers, SIGNATURE_HEADER) else {
        return Provenance::Invalid;
    };
    let Some(signed_at) = header_str(headers, SIGNED_AT_HEADER) else {
        return Provenance::Invalid;
    };

    let body_digest = hex::encode(Sha256::digest(request.body));
    let message = canonical(&[
        request.token,
        request.signature_scope,
        request.content_type,
        request.content_encoding,
        &body_digest,
        &signed_at,
    ]);
    if !verify_hmac(secret.as_bytes(), &message, &signature) {
        return Provenance::Invalid;
    }
    if is_fresh(&signed_at, now) {
        Provenance::Verified
    } else {
        Provenance::Stale
    }
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
        properties.retain(|key, _| !key.starts_with(GATEWAY_PREFIX));
        if trusted {
            properties.insert(VERIFIED_PROPERTY.to_string(), Value::Bool(true));
            properties.insert(RELAY_PROPERTY.to_string(), Value::Bool(true));
        }
    }
    counter!(PROVENANCE_METRIC, "reason" => reason).increment(1);
}

fn header_str(headers: &HeaderMap, name: &str) -> Option<String> {
    headers.get(name)?.to_str().ok().map(str::to_owned)
}

fn canonical(fields: &[&str]) -> Vec<u8> {
    let mut buffer = Vec::with_capacity(fields.iter().map(|field| field.len() + 4).sum());
    for field in fields {
        buffer.extend_from_slice(&(field.len() as u32).to_be_bytes());
        buffer.extend_from_slice(field.as_bytes());
    }
    buffer
}

fn verify_hmac(secret: &[u8], message: &[u8], signature_hex: &str) -> bool {
    let Ok(expected) = hex::decode(signature_hex) else {
        return false;
    };
    let Ok(mut mac) = HmacSha256::new_from_slice(secret) else {
        return false;
    };
    mac.update(message);
    mac.verify_slice(&expected).is_ok()
}

fn is_fresh(signed_at: &str, now: DateTime<Utc>) -> bool {
    let Ok(signed_at) = DateTime::parse_from_rfc3339(signed_at) else {
        return false;
    };
    let skew = now.signed_duration_since(signed_at.with_timezone(&Utc));
    skew.abs() <= Duration::seconds(FRESHNESS_WINDOW_SECS)
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
        headers.insert(SIGNATURE_HEADER, SIGNATURE.parse().unwrap());
        headers.insert(SIGNED_AT_HEADER, SIGNED_AT.parse().unwrap());
        headers
    }

    #[test]
    fn accepts_gateway_known_answer_vector() {
        assert_eq!(
            verify(
                &signed_headers(),
                Some(SECRET),
                now(),
                SignedRequest {
                    token: TOKEN,
                    content_type: "application/x-protobuf",
                    content_encoding: "gzip",
                    body: BODY,
                    signature_scope: TRACE_SIGNATURE_SCOPE,
                },
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
                now(),
                SignedRequest {
                    token: TOKEN,
                    content_type: "application/x-protobuf",
                    content_encoding: "gzip",
                    body: b"tampered",
                    signature_scope: TRACE_SIGNATURE_SCOPE,
                },
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
                now() + Duration::seconds(FRESHNESS_WINDOW_SECS + 1),
                SignedRequest {
                    token: TOKEN,
                    content_type: "application/x-protobuf",
                    content_encoding: "gzip",
                    body: BODY,
                    signature_scope: TRACE_SIGNATURE_SCOPE,
                },
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
        assert_eq!(properties.get(VERIFIED_PROPERTY), Some(&Value::Bool(true)));
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
        assert!(!properties.contains_key(VERIFIED_PROPERTY));
        assert!(!properties.contains_key(RELAY_PROPERTY));
        assert_eq!(properties.get("$ai_trace_id"), Some(&json!("trace-1")));
    }
}
