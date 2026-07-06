//! Per-team request/response body logging for the `/flags` endpoint.
//!
//! Configured via the `FLAGS_LOG_BODIES_TEAMS` env var at startup and refreshed
//! at runtime from `posthog_instancesetting`
//! (key: `constance:posthog:FLAGS_LOG_BODIES_TEAMS`) every ~60s.
//!
//! Stored per-team config maps a team ID to a non-empty list of glob patterns;
//! the response's `flags` map is filtered to keys matching any pattern. To
//! capture every flag (rare and noisy), specify `["*"]` explicitly.
//!
//! Patterns support `*` wildcards (e.g., `my-feature`, `checkout-*`,
//! `*-targeting-*`); exact keys (no `*`) match by string equality.

use crate::api::instance_setting::{constance_key, fetch_instance_setting_raw_value};
use crate::api::types::{FlagDetails, FlagsResponse};
use crate::config::BodyLogTeams;
use crate::metrics::consts::FLAG_BODY_LOG_REFRESH_TOTAL;
use arc_swap::ArcSwap;
use bytes::Bytes;
use common_types::TeamId;
use once_cell::sync::Lazy;
use rand::Rng;
use regex::Regex;
use serde::Serialize;
use sqlx::PgPool;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tracing::warn;
use uuid::Uuid;

/// Refresh interval for the in-memory team config; matches the Django-side
/// `RATE_LIMITING_ALLOW_LIST_TEAMS` cadence so admins see propagation in <1m.
const REFRESH_INTERVAL: Duration = Duration::from_secs(60);

/// Tracing target for body-log events. Stable identifier independent of the
/// module path; promoted to a Loki label for differential retention and used
/// in `main.rs` to keep these events out of the OpenTelemetry sink.
pub const BODY_LOG_TARGET: &str = "feature_flags::flags_body_log";

static CONSTANCE_KEY: Lazy<String> = Lazy::new(|| constance_key("FLAGS_LOG_BODIES_TEAMS"));

/// Compiles a glob-style pattern (`*` wildcard, no other metacharacters) into
/// an anchored regex. Exact keys (no `*`) compile to `^literal$`.
fn compile_pattern(raw: &str) -> Result<Regex, regex::Error> {
    let escaped = regex::escape(raw).replace("\\*", ".*");
    Regex::new(&format!("^{escaped}$"))
}

/// Per-team body-logging filter. Holds the joined pattern strings (for the
/// `response_filter_patterns` log field) and their compiled regexes (for
/// matching). The parser guarantees `compiled` is non-empty; an operator who
/// truly wants every flag must specify `["*"]` explicitly.
#[derive(Debug)]
pub struct TeamPatterns {
    /// Original patterns pre-joined with `,` for the log field; built once at
    /// refresh time so the opt-in path doesn't allocate per request.
    raw_joined: String,
    compiled: Vec<Regex>,
}

impl TeamPatterns {
    fn new(raw: Vec<String>) -> Self {
        let raw_joined = raw.join(",");
        let compiled = raw
            .iter()
            .filter_map(|p| match compile_pattern(p) {
                Ok(re) => Some(re),
                Err(e) => {
                    warn!(pattern = %p, error = %e, "invalid FLAGS_LOG_BODIES_TEAMS pattern, skipping");
                    None
                }
            })
            .collect();
        Self {
            raw_joined,
            compiled,
        }
    }

    /// True when `key` matches one of the configured patterns.
    pub fn matches(&self, key: &str) -> bool {
        self.compiled.iter().any(|re| re.is_match(key))
    }
}

/// In-memory body-logging config, refreshed periodically from Postgres by a
/// background task spawned via [`BodyLogger::spawn_refresh_task`].
///
/// `config` uses [`ArcSwap`] so the request hot path is a single atomic load
/// — no `RwLock`, so a panic in the refresh task can't poison a lock the hot
/// path then walks into. `last_applied` is touched only by the single-threaded
/// refresh task, so its `Mutex` is uncontended.
///
/// On persistent Postgres failure, the refresh task keeps ticking every
/// `REFRESH_INTERVAL` and the cached config is held indefinitely — fail-static
/// rather than fail-open. Operators should alert on absence of
/// `FLAG_BODY_LOG_REFRESH_TOTAL{result="success"}` increments rather than
/// expecting the process to surface a hard failure.
pub struct BodyLogger {
    config: ArcSwap<HashMap<TeamId, Arc<TeamPatterns>>>,
    /// Last `BodyLogTeams` we successfully applied. Used to skip the
    /// recompile when the DB row is unchanged so concurrent readers retain
    /// `Arc<TeamPatterns>` identity across no-op refreshes.
    last_applied: Mutex<Option<BodyLogTeams>>,
    /// Cheap short-circuit for the common no-team-enabled path. Tracks
    /// whether the config map is non-empty so per-request lookups can skip
    /// the `ArcSwap` load entirely. Updated alongside `config`.
    any_enabled: AtomicBool,
    /// Maximum request body bytes to log; bodies above this are truncated.
    request_max_bytes: usize,
}

impl BodyLogger {
    pub fn new(initial: BodyLogTeams, request_max_bytes: usize) -> Self {
        let map = compile_all(&initial);
        let any_enabled = AtomicBool::new(!map.is_empty());
        Self {
            config: ArcSwap::from(Arc::new(map)),
            last_applied: Mutex::new(Some(initial)),
            any_enabled,
            request_max_bytes,
        }
    }

    /// True when at least one team is in the allow-list. Lets callers skip
    /// per-request work (body clone, ArcSwap load) in the common case.
    pub fn has_any_enabled(&self) -> bool {
        self.any_enabled.load(Ordering::Relaxed)
    }

    /// Returns the per-team filter, or `None` when the team isn't enabled.
    pub fn for_team(&self, team_id: TeamId) -> Option<Arc<TeamPatterns>> {
        if !self.has_any_enabled() {
            return None;
        }
        self.config.load().get(&team_id).cloned()
    }

    fn update(&self, raw: BodyLogTeams) {
        let mut last_applied = self
            .last_applied
            .lock()
            .expect("body logger last_applied poisoned");
        if last_applied.as_ref() == Some(&raw) {
            return;
        }
        let map = compile_all(&raw);
        self.any_enabled.store(!map.is_empty(), Ordering::Relaxed);
        self.config.store(Arc::new(map));
        *last_applied = Some(raw);
    }

    /// Spawn a background task that refreshes the in-memory config from
    /// Postgres on `REFRESH_INTERVAL`. The task sleeps a random startup
    /// jitter in `[0, REFRESH_INTERVAL)` before the first refresh so a
    /// coordinated deploy (N pods booting together) smears its initial DB
    /// queries across the interval instead of all hitting Postgres in the
    /// same scheduler hop. The task runs for the lifetime of the runtime;
    /// on graceful shutdown the runtime cancels it.
    ///
    /// `MissedTickBehavior::Delay` keeps the steady-state cadence after a
    /// runtime stall (clock jump, host suspend) instead of firing a flurry
    /// of catch-up refreshes against a recovering DB.
    pub fn spawn_refresh_task(self: Arc<Self>, pool: Arc<PgPool>) {
        let jitter = Duration::from_millis(
            rand::thread_rng().gen_range(0..REFRESH_INTERVAL.as_millis() as u64),
        );
        tokio::spawn(async move {
            tokio::time::sleep(jitter).await;
            let mut ticker = tokio::time::interval(REFRESH_INTERVAL);
            ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            loop {
                ticker.tick().await;
                self.do_refresh(&pool).await;
            }
        });
    }

    /// Fetch the body-log config from the database and apply it.
    /// Best-effort: on DB error, the cached config is kept and a warning is
    /// logged. Each attempt increments `FLAG_BODY_LOG_REFRESH_TOTAL` labeled
    /// by `result="success"|"failure"` so operators can alert on absence of
    /// recent successes.
    pub async fn do_refresh(&self, pool: &PgPool) {
        let result_label = match fetch_from_db(pool).await {
            Ok(Some(raw)) => {
                self.update(raw);
                "success"
            }
            Ok(None) => {
                // Row absent: keep cached value (env-var default or prior refresh).
                "success"
            }
            Err(e) => {
                warn!(
                    error = %e,
                    "Failed to refresh FLAGS_LOG_BODIES_TEAMS from database, keeping cached value"
                );
                "failure"
            }
        };
        common_metrics::inc(
            FLAG_BODY_LOG_REFRESH_TOTAL,
            &[("result".to_string(), result_label.to_string())],
            1,
        );
    }

    /// Emit a tracing record on target `feature_flags::flags_body_log` when
    /// `team_id` resolves to an opted-in team. No-op otherwise.
    ///
    /// `decoded_body` is the post-gzip, post-base64 request body captured
    /// during normal request decoding (see [`RequestContext`] and
    /// [`crate::handler::authentication::parse_and_authenticate`]). Reusing
    /// those bytes means opted-in teams using gzip don't pay for a second
    /// decompress, and base64-wrapped bodies are logged as the JSON they
    /// actually parsed as — not as the raw base64 string.
    pub fn log_response(
        &self,
        request_id: Uuid,
        team_id: Option<TeamId>,
        decoded_body: Option<Bytes>,
        response: &FlagsResponse,
    ) {
        let (Some(team_id), Some(decoded)) = (team_id, decoded_body) else {
            return;
        };
        let Some(patterns) = self.for_team(team_id) else {
            return;
        };

        let (truncated, request_truncated, request_original_size_bytes) =
            truncate_body(&decoded, self.request_max_bytes);
        let request_body = String::from_utf8_lossy(truncated);
        let (response_flags_body, total, logged) = serialize_filtered_response(response, &patterns);

        // Override the default target (module path) with a stable, semantic
        // identifier. Keeps the `feature_flags::` prefix so `RUST_LOG` filters
        // and prefix-based tooling continue to match. This is the discriminator
        // forwarders can promote to a Loki label for differential retention.
        // Loki joins this record to the canonical log line on `request_id`.
        tracing::info!(
            target: BODY_LOG_TARGET,
            request_id = %request_id,
            team_id = team_id,
            request_body = %request_body,
            response_flags_body = %response_flags_body,
            request_truncated = request_truncated,
            request_original_size_bytes = request_original_size_bytes,
            response_filter_patterns = %patterns.raw_joined,
            response_flag_count_total = total,
            response_flag_count_logged = logged,
            "logged",
        );
    }
}

fn compile_all(raw: &BodyLogTeams) -> HashMap<TeamId, Arc<TeamPatterns>> {
    raw.0
        .iter()
        .map(|(team_id, patterns)| (*team_id, Arc::new(TeamPatterns::new(patterns.clone()))))
        .collect()
}

async fn fetch_from_db(pool: &PgPool) -> Result<Option<BodyLogTeams>, String> {
    let raw = match fetch_instance_setting_raw_value(pool, &CONSTANCE_KEY).await? {
        Some(v) => v,
        None => return Ok(None),
    };
    raw.parse::<BodyLogTeams>().map(Some)
}

/// Truncate a body to `max_bytes`, returning the prefix slice, whether it was
/// truncated, and the original byte length. Respects UTF-8 char boundaries
/// (RFC 3629) so the resulting slice is safe to pass to `from_utf8_lossy`
/// without splitting a multi-byte sequence.
pub(crate) fn truncate_body(body: &[u8], max_bytes: usize) -> (&[u8], bool, usize) {
    let original_len = body.len();
    if original_len <= max_bytes {
        return (body, false, original_len);
    }

    let mut end = max_bytes;
    while end > 0 {
        match std::str::from_utf8(&body[..end]) {
            Ok(_) => break,
            Err(e) => end = e.valid_up_to(),
        }
    }
    (&body[..end], true, original_len)
}

/// Subset of `FlagsResponse` we emit on the body-log line. The flattened
/// `ConfigResponse` (sessionRecording, surveys, siteApps, toolbarParams) is
/// intentionally omitted: it can be tens of KB per response and is unrelated
/// to flag debugging. The corresponding log field is named
/// `response_flags_body` to document the omission at the use site.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LoggedResponse<'a> {
    errors_while_computing_flags: bool,
    flags: HashMap<&'a String, &'a FlagDetails>,
    #[serde(skip_serializing_if = "Option::is_none")]
    quota_limited: &'a Option<Vec<String>>,
    request_id: Uuid,
    evaluated_at: i64,
}

/// Serialize the response with `flags` filtered to keys matching `patterns`.
/// Returns the JSON string plus `(total_flags, logged_flags)` counts.
fn serialize_filtered_response(
    response: &FlagsResponse,
    patterns: &TeamPatterns,
) -> (String, usize, usize) {
    let total = response.flags.len();

    let flags: HashMap<&String, &FlagDetails> = response
        .flags
        .iter()
        .filter(|(key, _)| patterns.matches(key))
        .collect();
    let logged = flags.len();

    let payload = LoggedResponse {
        errors_while_computing_flags: response.errors_while_computing_flags,
        flags,
        quota_limited: &response.quota_limited,
        request_id: response.request_id,
        evaluated_at: response.evaluated_at,
    };

    let body = match serde_json::to_string(&payload) {
        Ok(s) => s,
        Err(e) => {
            warn!(error = %e, "flags_body_log response serialize failed, emitting sentinel");
            "<serialize-failed>".to_string()
        }
    };
    (body, total, logged)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::types::{
        FlagDetails, FlagDetailsMetadata, FlagEvaluationReason, FlagsResponse,
    };
    use std::collections::HashMap;
    use uuid::Uuid;

    fn make_flag(key: &str, enabled: bool) -> FlagDetails {
        FlagDetails {
            key: key.to_string(),
            enabled,
            variant: None,
            failed: false,
            reason: FlagEvaluationReason {
                code: "matched".to_string(),
                description: None,
                condition_index: None,
            },
            metadata: FlagDetailsMetadata {
                id: 1,
                version: 1,
                description: None,
                payload: None,
                has_experiment: false,
            },
            conditions: None,
        }
    }

    fn make_response(flag_keys: &[&str]) -> FlagsResponse {
        let mut flags = HashMap::new();
        for k in flag_keys {
            flags.insert(k.to_string(), make_flag(k, true));
        }
        FlagsResponse::new(false, flags, None, Uuid::nil())
    }

    fn matches(pattern: &str, key: &str) -> bool {
        compile_pattern(pattern).unwrap().is_match(key)
    }

    #[test]
    fn pattern_matching() {
        let cases: &[(&str, &str, bool)] = &[
            // Exact match.
            ("my-feature", "my-feature", true),
            ("my-feature", "my-feature-2", false),
            ("my-feature", "not-my-feature", false),
            // Prefix wildcard.
            ("checkout-*", "checkout-foo", true),
            ("checkout-*", "checkout-", true),
            ("checkout-*", "checkout-bar-baz", true),
            ("checkout-*", "checkou", false),
            ("checkout-*", "not-checkout-x", false),
            // Suffix wildcard.
            ("*-targeting", "survey-targeting", true),
            ("*-targeting", "-targeting", true),
            ("*-targeting", "targeting-other", false),
            // Middle wildcard.
            ("survey-*-targeting", "survey-abc-targeting", true),
            ("survey-*-targeting", "survey--targeting", true),
            ("survey-*-targeting", "survey-abc-other", false),
            ("survey-*-targeting", "not-survey-abc-targeting", false),
            // Match-all wildcard.
            ("*", "", true),
            ("*", "anything", true),
            ("*", "with-dashes-123", true),
        ];

        for (pattern, key, expected) in cases {
            assert_eq!(
                matches(pattern, key),
                *expected,
                "pattern={pattern:?} key={key:?}"
            );
        }
    }

    #[test]
    fn for_team_skip_when_unlisted() {
        let logger = BodyLogger::new(BodyLogTeams::default(), 65_536);
        assert!(!logger.has_any_enabled());
        assert!(logger.for_team(42).is_none());
    }

    #[test]
    fn for_team_log_all_when_wildcard_pattern() {
        let mut map = HashMap::new();
        map.insert(42, vec!["*".into()]);
        let logger = BodyLogger::new(BodyLogTeams(map), 65_536);
        assert!(logger.has_any_enabled());
        let p = logger.for_team(42).expect("expected entry for team 42");
        assert!(p.matches("anything-goes"));
        assert!(p.matches("checkout-foo"));
    }

    #[test]
    fn for_team_log_matching_when_patterns_set() {
        let mut map = HashMap::new();
        map.insert(42, vec!["my-feature".into(), "checkout-*".into()]);
        let logger = BodyLogger::new(BodyLogTeams(map), 65_536);
        let p = logger.for_team(42).expect("expected entry for team 42");
        assert_eq!(p.raw_joined, "my-feature,checkout-*");
        assert!(p.matches("my-feature"));
        assert!(p.matches("checkout-foo"));
        assert!(!p.matches("other-flag"));
    }

    #[test]
    fn serialize_filtered_response_passes_all_when_wildcard() {
        let resp = make_response(&["a", "b", "c"]);
        let patterns = TeamPatterns::new(vec!["*".into()]);
        let (_body, total, logged) = serialize_filtered_response(&resp, &patterns);
        assert_eq!(total, 3);
        assert_eq!(logged, 3);
    }

    #[test]
    fn serialize_filtered_response_filters_to_matching() {
        let resp = make_response(&["my-feature", "checkout-foo", "other"]);
        let patterns = TeamPatterns::new(vec!["my-feature".into(), "checkout-*".into()]);
        let (_body, total, logged) = serialize_filtered_response(&resp, &patterns);
        assert_eq!(total, 3);
        assert_eq!(logged, 2);
    }

    #[test]
    fn serialize_filtered_response_zero_when_no_match() {
        let resp = make_response(&["a", "b"]);
        let patterns = TeamPatterns::new(vec!["nothing-matches-*".into()]);
        let (_body, total, logged) = serialize_filtered_response(&resp, &patterns);
        assert_eq!(total, 2);
        assert_eq!(logged, 0);
    }

    #[test]
    fn truncate_body_under_cap() {
        let (out, truncated, original) = truncate_body(b"hello", 10);
        assert_eq!(out, b"hello");
        assert!(!truncated);
        assert_eq!(original, 5);
    }

    #[test]
    fn truncate_body_at_cap() {
        let (out, truncated, original) = truncate_body(b"hello", 5);
        assert_eq!(out, b"hello");
        assert!(!truncated);
        assert_eq!(original, 5);
    }

    #[test]
    fn truncate_body_over_cap() {
        let (out, truncated, original) = truncate_body(b"hello world", 5);
        assert_eq!(out, b"hello");
        assert!(truncated);
        assert_eq!(original, 11);
    }

    #[test]
    fn truncate_body_respects_utf8_boundary() {
        // "héllo" — é is 2 bytes (0xC3 0xA9). Cap at 2 must not split it.
        let body = "héllo".as_bytes();
        let (out, truncated, _) = truncate_body(body, 2);
        assert_eq!(out, b"h");
        assert!(truncated);
    }

    #[test]
    fn body_log_teams_parses_empty() {
        assert!("{}".parse::<BodyLogTeams>().unwrap().0.is_empty());
        assert!("".parse::<BodyLogTeams>().unwrap().0.is_empty());
    }

    #[test]
    fn body_log_teams_parses_populated() {
        let parsed: BodyLogTeams = r#"{"123": ["*"], "456": ["my-feature", "checkout-*"]}"#
            .parse()
            .unwrap();
        assert_eq!(parsed.0.len(), 2);
        assert_eq!(parsed.0[&123], vec!["*"]);
        assert_eq!(parsed.0[&456], vec!["my-feature", "checkout-*"]);
    }

    #[test]
    fn body_log_teams_rejects_invalid_team_id() {
        let result: Result<BodyLogTeams, _> = r#"{"abc": ["*"]}"#.parse();
        assert!(result.is_err());
    }

    #[test]
    fn body_log_teams_rejects_empty_patterns_for_team() {
        let err = r#"{"42": []}"#.parse::<BodyLogTeams>().unwrap_err();
        assert!(err.contains("Team 42 has no patterns"));
        assert!(err.contains(r#"["*"]"#));
    }

    #[test]
    fn body_log_teams_rejects_too_many_teams() {
        use crate::config::MAX_BODY_LOG_TEAMS;
        let mut entries = String::from("{");
        for i in 0..=MAX_BODY_LOG_TEAMS {
            if i > 0 {
                entries.push(',');
            }
            entries.push_str(&format!(r#""{i}": ["*"]"#));
        }
        entries.push('}');
        let err = entries.parse::<BodyLogTeams>().unwrap_err();
        assert!(err.contains("Too many FLAGS_LOG_BODIES_TEAMS entries"));
    }

    #[test]
    fn body_log_teams_rejects_too_many_patterns_per_team() {
        use crate::config::MAX_BODY_LOG_PATTERNS_PER_TEAM;
        let patterns: Vec<String> = (0..=MAX_BODY_LOG_PATTERNS_PER_TEAM)
            .map(|i| format!(r#""p{i}""#))
            .collect();
        let json = format!(r#"{{"42": [{}]}}"#, patterns.join(","));
        let err = json.parse::<BodyLogTeams>().unwrap_err();
        assert!(err.contains("Too many patterns for team 42"));
    }

    #[test]
    fn body_log_teams_rejects_pattern_too_long() {
        use crate::config::MAX_BODY_LOG_PATTERN_LEN;
        let big = "a".repeat(MAX_BODY_LOG_PATTERN_LEN + 1);
        let json = format!(r#"{{"42": ["{big}"]}}"#);
        let err = json.parse::<BodyLogTeams>().unwrap_err();
        assert!(err.contains("Pattern too long for team 42"));
    }

    #[test]
    fn update_skips_recompile_when_unchanged() {
        let mut map = HashMap::new();
        map.insert(42, vec!["foo".into()]);
        let logger = BodyLogger::new(BodyLogTeams(map.clone()), 65_536);
        let before = Arc::as_ptr(&logger.for_team(42).unwrap());
        logger.update(BodyLogTeams(map));
        let after = Arc::as_ptr(&logger.for_team(42).unwrap());
        assert_eq!(
            before, after,
            "Arc identity preserved when config unchanged"
        );
    }

    /// In-memory `MakeWriter` that captures emitted log lines so tests can
    /// assert the `flags_body_log` event shape without the JSON formatter
    /// going to stdout.
    #[derive(Clone, Default)]
    struct CaptureWriter(Arc<std::sync::Mutex<Vec<u8>>>);

    impl CaptureWriter {
        fn captured(&self) -> String {
            String::from_utf8(self.0.lock().unwrap().clone()).unwrap()
        }
    }

    impl std::io::Write for CaptureWriter {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            self.0.lock().unwrap().extend_from_slice(buf);
            Ok(buf.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for CaptureWriter {
        type Writer = Self;
        fn make_writer(&'a self) -> Self::Writer {
            self.clone()
        }
    }

    fn capture_log_response<F: FnOnce(&CaptureWriter)>(f: F) -> String {
        let writer = CaptureWriter::default();
        let subscriber = tracing_subscriber::fmt()
            .json()
            .with_writer(writer.clone())
            .with_max_level(tracing::Level::INFO)
            .finish();
        tracing::subscriber::with_default(subscriber, || f(&writer));
        writer.captured()
    }

    #[test]
    fn log_response_emits_event_for_opted_in_team() {
        let mut map = HashMap::new();
        map.insert(42, vec!["*".into()]);
        let logger = BodyLogger::new(BodyLogTeams(map), 65_536);
        let resp = make_response(&["my-feature"]);

        let captured = capture_log_response(|_| {
            logger.log_response(
                Uuid::nil(),
                Some(42),
                Some(Bytes::from_static(b"{\"token\":\"phc_abc\"}")),
                &resp,
            );
        });

        assert!(
            captured.contains("flags_body_log"),
            "expected target in log line: {captured}"
        );
        assert!(
            captured.contains("\"team_id\":42"),
            "expected team_id field: {captured}"
        );
        assert!(
            captured.contains("\"response_flag_count_total\":1"),
            "expected total count: {captured}"
        );
        assert!(
            captured.contains("\"response_flag_count_logged\":1"),
            "expected logged count: {captured}"
        );
        assert!(
            captured.contains("phc_abc"),
            "expected request body to be logged: {captured}"
        );
    }

    #[test]
    fn log_response_skips_unopted_team() {
        let logger = BodyLogger::new(BodyLogTeams::default(), 65_536);
        let resp = make_response(&["a"]);

        let captured = capture_log_response(|_| {
            logger.log_response(Uuid::nil(), Some(42), Some(Bytes::from_static(b"x")), &resp);
        });

        assert!(
            !captured.contains("flags_body_log"),
            "unopted team should produce no event: {captured}"
        );
    }

    #[test]
    fn log_response_skips_when_team_id_missing() {
        let mut map = HashMap::new();
        map.insert(42, vec!["*".into()]);
        let logger = BodyLogger::new(BodyLogTeams(map), 65_536);
        let resp = make_response(&["a"]);

        let captured = capture_log_response(|_| {
            logger.log_response(Uuid::nil(), None, Some(Bytes::from_static(b"x")), &resp);
        });

        assert!(
            !captured.contains("flags_body_log"),
            "missing team_id should produce no event: {captured}"
        );
    }

    #[test]
    fn log_response_includes_filter_metadata_when_patterns_set() {
        let mut map = HashMap::new();
        map.insert(42, vec!["my-feature".into(), "checkout-*".into()]);
        let logger = BodyLogger::new(BodyLogTeams(map), 65_536);
        let resp = make_response(&["my-feature", "checkout-foo", "other"]);

        let captured = capture_log_response(|_| {
            logger.log_response(
                Uuid::nil(),
                Some(42),
                Some(Bytes::from_static(b"{}")),
                &resp,
            );
        });

        assert!(captured.contains("\"response_filter_patterns\":\"my-feature,checkout-*\""));
        assert!(captured.contains("\"response_flag_count_total\":3"));
        assert!(captured.contains("\"response_flag_count_logged\":2"));
    }

    #[test]
    fn log_response_omits_config_response_fields() {
        // ConfigResponse (sessionRecording, surveys, siteApps, toolbarParams)
        // is intentionally excluded from the logged response — flag debugging
        // does not need it and including it makes the log line unbounded.
        let mut map = HashMap::new();
        map.insert(42, vec!["*".into()]);
        let logger = BodyLogger::new(BodyLogTeams(map), 65_536);

        let mut resp = make_response(&["my-feature"]);
        resp.config
            .set("sessionRecording", serde_json::json!(false));
        resp.config
            .set("toolbarParams", serde_json::json!({"foo": "bar"}));

        let captured = capture_log_response(|_| {
            logger.log_response(
                Uuid::nil(),
                Some(42),
                Some(Bytes::from_static(b"{}")),
                &resp,
            );
        });

        assert!(
            !captured.contains("sessionRecording"),
            "config flatten leaked into log: {captured}"
        );
        assert!(
            !captured.contains("toolbarParams"),
            "config flatten leaked into log: {captured}"
        );
        // The flag itself should still be present.
        assert!(
            captured.contains("my-feature"),
            "expected flag key in log: {captured}"
        );
    }

    #[test]
    fn serialize_filtered_response_filters_correct_keys() {
        let resp = make_response(&["my-feature", "checkout-foo", "other"]);
        let patterns = TeamPatterns::new(vec!["my-feature".into(), "checkout-*".into()]);
        let (body, total, logged) = serialize_filtered_response(&resp, &patterns);
        assert_eq!(total, 3);
        assert_eq!(logged, 2);
        assert!(body.contains("\"my-feature\""));
        assert!(body.contains("\"checkout-foo\""));
        assert!(!body.contains("\"other\""));
    }

    #[test]
    fn truncate_body_caps_below_first_multibyte_char_returns_empty() {
        // "é" is 2 bytes (0xC3 0xA9). Cap of 1 falls inside the char, so
        // `valid_up_to()` returns 0 and we end up with an empty prefix.
        let body = "é".as_bytes();
        let (out, truncated, original) = truncate_body(body, 1);
        assert_eq!(out, b"");
        assert!(truncated);
        assert_eq!(original, 2);
    }
}
