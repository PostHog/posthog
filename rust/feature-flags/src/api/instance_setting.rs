//! Shared helpers for reading Django Constance dynamic settings stored in
//! `posthog_instancesetting`.
//!
//! Django writes settings under the key `constance:posthog:<NAME>` with one
//! of three encodings, depending on history and value type:
//! - JSON-encoded string (`"\"foo\""`) — the common case when `set_constance_value`
//!   went through Django's serializer.
//! - JSON `null` — explicit "no value" written by some admin paths.
//! - Bare string — older rows or values written outside the serializer.
//!
//! Callers want the unwrapped inner value to feed into their own parser
//! (CSV, JSON, etc.). This helper consolidates that decoding so each caller
//! only owns its parse step.
use sqlx::PgPool;

const CONSTANCE_PREFIX: &str = "constance:posthog:";

/// Build the full Postgres key for a Constance setting name.
pub fn constance_key(setting_name: &str) -> String {
    format!("{CONSTANCE_PREFIX}{setting_name}")
}

/// Fetch a Constance dynamic setting from `posthog_instancesetting`, returning
/// the unwrapped raw string value.
///
/// - `Ok(None)` — row missing; callers should keep their env-var default.
/// - `Ok(Some(""))` — row exists with `null` or empty raw value; callers
///   typically treat this as "explicitly empty".
/// - `Ok(Some(s))` — unwrapped value, ready for caller-specific parsing.
pub async fn fetch_instance_setting_raw_value(
    pool: &PgPool,
    full_key: &str,
) -> Result<Option<String>, String> {
    let row: Option<(String,)> =
        sqlx::query_as("SELECT raw_value FROM posthog_instancesetting WHERE key = $1")
            .bind(full_key)
            .fetch_optional(pool)
            .await
            .map_err(|e| format!("DB query failed: {e}"))?;

    let raw_value = match row {
        Some((val,)) => val,
        None => return Ok(None),
    };

    let unwrapped = match serde_json::from_str::<serde_json::Value>(&raw_value) {
        Ok(serde_json::Value::String(s)) => s,
        Ok(serde_json::Value::Null) => String::new(),
        // For other JSON shapes (numbers, bools, arrays, objects) return the
        // raw bytes from the DB rather than re-serialising via serde, so
        // whitespace and formatting survive a round-trip.
        Ok(_) => raw_value,
        Err(_) => raw_value,
    };

    Ok(Some(unwrapped))
}
