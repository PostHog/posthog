//! Port of `nodejs/src/logs/internal-logs.ts`: the signed `posthog-internal` header that marks a
//! batch from a PostHog-owned producer.

use std::collections::HashMap;

use hmac::{Hmac, Mac};
use metrics::counter;
use sha2::Sha256;

use crate::js::{date_parse, json_stringify, number_to_string, JsValue};
use crate::property_filter::coerce::{js_parse_int, js_trim};

pub const INTERNAL_LOGS_HEADER: &str = "posthog-internal";
/// The HTTP request header that capture-logs forwards as `posthog-internal`.
pub const INTERNAL_LOGS_HTTP_HEADER: &str = "x-posthog-internal";
pub const INTERNAL_SOURCE_HEADER: &str = "internal-source";

const SIGNATURE_VERSION: &str = "v1";
/// Measured against capture's `created_at`, so consumer lag does not expire a signature.
const SIGNATURE_WINDOW_SECONDS: f64 = 5.0 * 60.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InternalSourcePolicy {
    /// Counts toward the team's usage, quota and rate limits.
    pub billed: bool,
    /// Runs the team's sampling, drop, transformation, metric and retention rules.
    pub team_rules: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InternalLogs {
    pub source: String,
    pub billed: bool,
    pub team_rules: bool,
}

pub fn default_internal_source_policies() -> HashMap<String, InternalSourcePolicy> {
    HashMap::from([(
        "hog_flow".to_string(),
        InternalSourcePolicy {
            billed: false,
            team_rules: false,
        },
    )])
}

/// `/^[a-z0-9_]{1,64}$/`.
fn is_valid_source(source: &str) -> bool {
    (1..=64).contains(&source.len())
        && source
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

/// `/^[1-9][0-9]{9}$/`: epoch seconds with no sign, padding or fraction.
fn is_valid_signed_at(signed_at: &str) -> bool {
    let b = signed_at.as_bytes();
    b.len() == 10 && (b'1'..=b'9').contains(&b[0]) && b[1..].iter().all(u8::is_ascii_digit)
}

fn parse_keys(comma_separated_keys: &str) -> Vec<String> {
    comma_separated_keys
        .split(',')
        .map(js_trim)
        .filter(|k| !k.is_empty())
        .map(str::to_string)
        .collect()
}

fn compute_signature(key: &str, source: &str, team_id: i64, signed_at: &str) -> String {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(key.as_bytes()).expect("HMAC takes a key of any length");
    mac.update(format!("{SIGNATURE_VERSION}|{source}|{team_id}|{signed_at}").as_bytes());
    let digest = hex::encode(mac.finalize().into_bytes());
    format!("{SIGNATURE_VERSION}.{source}.{signed_at}.{digest}")
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SignError {
    NoKey,
    InvalidSource(String),
}

impl std::fmt::Display for SignError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SignError::NoKey => write!(
                f,
                "Cannot sign posthog-internal batch: no signing key configured"
            ),
            SignError::InvalidSource(source) => write!(
                f,
                "Cannot sign posthog-internal batch: invalid source {}",
                json_stringify(&JsValue::string(source))
            ),
        }
    }
}

impl std::error::Error for SignError {}

/// `signInternalLogs`, with the newest (first) key. `signed_at_ms` is `Date#getTime()`.
pub fn sign_internal_logs(
    comma_separated_keys: &str,
    source: &str,
    team_id: i64,
    signed_at_ms: f64,
) -> Result<String, SignError> {
    let keys = parse_keys(comma_separated_keys);
    let Some(newest) = keys.first() else {
        return Err(SignError::NoKey);
    };
    if !is_valid_source(source) {
        return Err(SignError::InvalidSource(source.to_string()));
    }
    let signed_at = number_to_string((signed_at_ms / 1000.0).floor());
    Ok(compute_signature(newest, source, team_id, &signed_at))
}

pub fn without_internal_logs_headers<I, K, V>(headers: I) -> Vec<(K, V)>
where
    I: IntoIterator<Item = (K, V)>,
    K: AsRef<str>,
{
    headers
        .into_iter()
        .filter(|(k, _)| k.as_ref() != INTERNAL_LOGS_HEADER && k.as_ref() != INTERNAL_SOURCE_HEADER)
        .collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum NotInternalReason {
    NotConfigured,
    TeamNotAllowed,
    InvalidSignature,
    StaleSignature,
    UnknownSource,
}

impl NotInternalReason {
    fn as_str(&self) -> &'static str {
        match self {
            NotInternalReason::NotConfigured => "not_configured",
            NotInternalReason::TeamNotAllowed => "team_not_allowed",
            NotInternalReason::InvalidSignature => "invalid_signature",
            NotInternalReason::StaleSignature => "stale_signature",
            NotInternalReason::UnknownSource => "unknown_source",
        }
    }
}

#[derive(Debug, Clone)]
enum TeamMatcher {
    None,
    All,
    Teams(Vec<f64>),
}

impl TeamMatcher {
    fn build(config: &str) -> TeamMatcher {
        if js_trim(config).is_empty() {
            TeamMatcher::None
        } else if config == "*" {
            TeamMatcher::All
        } else {
            // `parseInt(n)` with no radix: it skips leading whitespace and reads `0x` as hex.
            TeamMatcher::Teams(
                config
                    .split(',')
                    .map(|n| js_parse_int(n, None))
                    .filter(|n| !n.is_nan())
                    .collect(),
            )
        }
    }

    fn matches(&self, team_id: i64) -> bool {
        match self {
            TeamMatcher::None => false,
            TeamMatcher::All => true,
            TeamMatcher::Teams(ids) => ids.contains(&(team_id as f64)),
        }
    }
}

#[derive(Debug, Clone)]
pub struct InternalLogsVerifier {
    keys: Vec<String>,
    is_team_allowed: TeamMatcher,
    policies: HashMap<String, InternalSourcePolicy>,
}

impl InternalLogsVerifier {
    pub fn new(
        comma_separated_keys: &str,
        enabled_teams: &str,
        policies: HashMap<String, InternalSourcePolicy>,
    ) -> Self {
        InternalLogsVerifier {
            keys: parse_keys(comma_separated_keys),
            is_team_allowed: TeamMatcher::build(enabled_teams),
            policies,
        }
    }

    /// `verify`. `created_at` is the `created_at` Kafka header that capture-logs sets.
    pub fn verify(
        &self,
        signature: Option<&str>,
        team_id: i64,
        created_at: Option<&str>,
    ) -> Option<InternalLogs> {
        let signature = signature?;
        let mut parts = signature.split('.');
        parts.next();
        let source = parts.next().unwrap_or("");
        let signed_at = parts.next().unwrap_or("");
        let reason = self.not_internal_reason(signature, source, signed_at, team_id, created_at);
        // Own keys only, so a source like `constructor` has no policy.
        let policy = match reason {
            None => self.policies.get(source),
            Some(_) => None,
        };
        let Some(policy) = policy else {
            let reason = reason.unwrap_or(NotInternalReason::UnknownSource).as_str();
            counter!("logs_ingestion_internal_logs_total", "outcome" => "not_internal", "reason" => reason).increment(1);
            tracing::warn!(
                team_id,
                reason,
                "Internal logs header did not verify, batch billed as normal"
            );
            return None;
        };
        counter!("logs_ingestion_internal_logs_total", "outcome" => "internal", "reason" => "")
            .increment(1);
        Some(InternalLogs {
            source: source.to_string(),
            billed: policy.billed,
            team_rules: policy.team_rules,
        })
    }

    fn not_internal_reason(
        &self,
        signature: &str,
        source: &str,
        signed_at: &str,
        team_id: i64,
        created_at: Option<&str>,
    ) -> Option<NotInternalReason> {
        if self.keys.is_empty() {
            return Some(NotInternalReason::NotConfigured);
        }
        if !self.is_team_allowed.matches(team_id) {
            return Some(NotInternalReason::TeamNotAllowed);
        }
        if !is_valid_source(source) || !is_valid_signed_at(signed_at) {
            return Some(NotInternalReason::InvalidSignature);
        }
        let received = signature.as_bytes();
        // Every key is tried, so a rotation can add a key before producers switch to it.
        let mut matches = false;
        for key in &self.keys {
            let expected = compute_signature(key, source, team_id, signed_at);
            matches |= constant_time_eq(expected.as_bytes(), received);
        }
        if !matches {
            return Some(NotInternalReason::InvalidSignature);
        }
        // A missing or unparseable `created_at` gives NaN, which fails the comparison.
        let created_ms = date_parse(created_at.unwrap_or("")).unwrap_or(f64::NAN);
        let signed_at_seconds: f64 = signed_at.parse().unwrap_or(f64::NAN);
        let skew = (created_ms / 1000.0 - signed_at_seconds).abs();
        if skew <= SIGNATURE_WINDOW_SECONDS {
            None
        } else {
            Some(NotInternalReason::StaleSignature)
        }
    }
}
