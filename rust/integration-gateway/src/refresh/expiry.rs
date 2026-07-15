use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::Value;

/// Whether an OAuth access token should be proactively refreshed, mirroring Django's
/// `OauthIntegration.access_token_expired`: refresh once past the half-life,
/// i.e. `now > refreshed_at + expires_in - expires_in/2`.
///
/// Returns false (never refresh) when the timing fields are absent — same as Django, which can't
/// judge expiry without them.
pub fn access_token_expired(kind: &str, config: &Value) -> bool {
    let refreshed_at = config.get("refreshed_at").and_then(Value::as_f64);
    let mut expires_in = config.get("expires_in").and_then(Value::as_f64);

    // Salesforce/Stripe often omit expires_in in their responses; Django assumes 3600s for them.
    if expires_in.is_none() && (kind == "salesforce" || kind == "stripe") {
        expires_in = Some(3600.0);
    }

    let (Some(expires_in), Some(refreshed_at)) = (expires_in, refreshed_at) else {
        return false;
    };
    if expires_in <= 0.0 {
        return false;
    }

    let threshold = expires_in / 2.0;
    now_secs() > refreshed_at + expires_in - threshold
}

/// Seconds since the Unix epoch as f64 (matches Django's `time.time()`).
pub fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn not_expired_without_timing_fields() {
        assert!(!access_token_expired("hubspot", &json!({})));
        assert!(!access_token_expired("hubspot", &json!({ "expires_in": 3600 })));
        assert!(!access_token_expired("hubspot", &json!({ "refreshed_at": 1000 })));
    }

    #[test]
    fn expired_past_half_life() {
        let now = now_secs();
        // refreshed 3000s ago, 3600s lifetime => 83% elapsed, past the 50% half-life threshold.
        let config = json!({ "expires_in": 3600, "refreshed_at": now - 3000.0 });
        assert!(access_token_expired("hubspot", &config));
    }

    #[test]
    fn fresh_before_half_life() {
        let now = now_secs();
        // refreshed 100s ago, 3600s lifetime => well before half-life.
        let config = json!({ "expires_in": 3600, "refreshed_at": now - 100.0 });
        assert!(!access_token_expired("hubspot", &config));
    }

    #[test]
    fn salesforce_defaults_expires_in() {
        let now = now_secs();
        // No expires_in, but Salesforce assumes 3600 => refreshed 3000s ago is past half-life.
        let config = json!({ "refreshed_at": now - 3000.0 });
        assert!(access_token_expired("salesforce", &config));
        // A non-defaulting kind with no expires_in never refreshes.
        assert!(!access_token_expired("hubspot", &config));
    }
}
