use axum::http::HeaderMap;
use chrono::{DateTime, Duration, Utc};
use hmac::{Hmac, Mac};
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

pub const SIGNATURE_HEADER: &str = "PostHog-Ai-Gateway-Signature";
pub const SIGNED_AT_HEADER: &str = "PostHog-Ai-Gateway-Signed-At";
pub const FRESHNESS_WINDOW_SECS: i64 = 5 * 60;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provenance {
    Verified,
    Stale,
    Invalid,
}

pub fn header_str(headers: &HeaderMap, name: &str) -> Option<String> {
    headers.get(name)?.to_str().ok().map(str::to_owned)
}

pub fn canonical(fields: &[&str]) -> Vec<u8> {
    let mut buffer = Vec::with_capacity(fields.iter().map(|field| field.len() + 4).sum());
    for field in fields {
        buffer.extend_from_slice(&(field.len() as u32).to_be_bytes());
        buffer.extend_from_slice(field.as_bytes());
    }
    buffer
}

pub fn verify(
    secret: &[u8],
    message: &[u8],
    signature_hex: &str,
    signed_at: &str,
    now: DateTime<Utc>,
) -> Provenance {
    let Ok(expected) = hex::decode(signature_hex) else {
        return Provenance::Invalid;
    };
    let Ok(mut mac) = HmacSha256::new_from_slice(secret) else {
        return Provenance::Invalid;
    };
    mac.update(message);
    if mac.verify_slice(&expected).is_err() {
        return Provenance::Invalid;
    }
    match DateTime::parse_from_rfc3339(signed_at) {
        Ok(value)
            if (now - value.with_timezone(&Utc)).abs()
                <= Duration::seconds(FRESHNESS_WINDOW_SECS) =>
        {
            Provenance::Verified
        }
        _ => Provenance::Stale,
    }
}

#[cfg(any(test, feature = "test-utils"))]
pub fn sign(secret: &[u8], fields: &[&str]) -> String {
    let mut mac = HmacSha256::new_from_slice(secret).expect("hmac accepts any key length");
    mac.update(&canonical(fields));
    hex::encode(mac.finalize().into_bytes())
}
