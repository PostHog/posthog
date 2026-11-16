use hmac::{Hmac, Mac};
use metrics::counter;
use sha2::Sha256;

use crate::internal_logs::{
    constant_time_eq, is_valid_signed_at, SIGNATURE_VERSION, SIGNATURE_WINDOW_SECONDS,
};
use crate::js::{date_parse, number_to_string};

pub const LOGS_SIGNATURE_HEADER: &str = "posthog-signature";
/// The Kafka MV copies this header to the `signature_status` column.
pub const SIGNATURE_STATUS_HEADER: &str = "signature-status";
pub const SIGNATURE_STATUS_VERIFIED: &str = "verified";

fn compute_signature(secret: &str, team_id: i64, signed_at: &str) -> String {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("HMAC takes a key of any length");
    mac.update(format!("{SIGNATURE_VERSION}|{team_id}|{signed_at}").as_bytes());
    let digest = hex::encode(mac.finalize().into_bytes());
    format!("{SIGNATURE_VERSION}.{signed_at}.{digest}")
}

pub fn sign_logs(secret: &str, team_id: i64, signed_at_ms: f64) -> String {
    let signed_at = number_to_string((signed_at_ms / 1000.0).floor());
    compute_signature(secret, team_id, &signed_at)
}

fn unverified_reason(
    signature: &str,
    secrets: &[String],
    team_id: i64,
    created_at: Option<&str>,
) -> Option<&'static str> {
    if secrets.is_empty() {
        return Some("no_secret");
    }
    let signed_at = signature.split('.').nth(1).unwrap_or("");
    if !is_valid_signed_at(signed_at) {
        return Some("invalid_signature");
    }
    let mut matches = false;
    for secret in secrets {
        let expected = compute_signature(secret, team_id, signed_at);
        matches |= constant_time_eq(expected.as_bytes(), signature.as_bytes());
    }
    if !matches {
        return Some("invalid_signature");
    }
    // A missing or unparseable `created_at` gives NaN, which fails the comparison.
    let created_ms = date_parse(created_at.unwrap_or("")).unwrap_or(f64::NAN);
    let signed_at_seconds: f64 = signed_at.parse().unwrap_or(f64::NAN);
    if (created_ms / 1000.0 - signed_at_seconds).abs() <= SIGNATURE_WINDOW_SECONDS {
        None
    } else {
        Some("stale_signature")
    }
}

/// `secrets` are the team's current secret, then the previous one while its grace period lasts.
/// `created_at` is the Kafka header that capture-logs sets.
pub fn verify_logs_signature(
    signature: &str,
    secrets: &[String],
    team_id: i64,
    created_at: Option<&str>,
) -> bool {
    let reason = unverified_reason(signature, secrets, team_id, created_at);
    let outcome = if reason.is_some() {
        "unverified"
    } else {
        "verified"
    };
    counter!("logs_ingestion_signature_total", "outcome" => outcome, "reason" => reason.unwrap_or(""))
        .increment(1);
    reason.is_none()
}

#[cfg(test)]
mod tests {
    use super::*;

    const NOW_MS: f64 = 1_800_000_000_000.0;
    const CREATED: &str = "2027-01-15T08:00:00.000Z";

    fn verify(signature: &str, secrets: &[&str], team_id: i64, created_at: Option<&str>) -> bool {
        let secrets: Vec<String> = secrets.iter().map(|s| s.to_string()).collect();
        verify_logs_signature(signature, &secrets, team_id, created_at)
    }

    #[test]
    fn verifies_only_a_fresh_signature_from_a_known_secret_for_the_same_team() {
        let signature = sign_logs("current", 7, NOW_MS);
        assert!(verify(&signature, &["current"], 7, Some(CREATED)));
        assert!(verify(
            &sign_logs("previous", 7, NOW_MS),
            &["current", "previous"],
            7,
            Some(CREATED)
        ));
        assert!(!verify(&signature, &[], 7, Some(CREATED)));
        assert!(!verify(&signature, &["other"], 7, Some(CREATED)));
        assert!(!verify(&signature, &["current"], 8, Some(CREATED)));
        assert!(!verify(&signature, &["current"], 7, None));
        assert!(!verify(
            &sign_logs("current", 7, NOW_MS - 3_600_000.0),
            &["current"],
            7,
            Some(CREATED)
        ));
        assert!(!verify("v1.not-a-time.abc", &["current"], 7, Some(CREATED)));
    }
}
