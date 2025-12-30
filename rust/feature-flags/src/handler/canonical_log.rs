use crate::api::errors::FlagError;
use std::cell::RefCell;
use std::future::Future;
use std::time::Instant;
use uuid::Uuid;

// Task-local storage for the canonical log line.
// This allows any code in the async task to access and modify the log
// without explicit parameter passing.
tokio::task_local! {
    static CANONICAL_LOG: RefCell<FlagsCanonicalLogLine>;
}

/// Safely modify the canonical log if one exists in scope.
/// No-ops silently if called outside a canonical log scope.
///
/// # Example
/// ```ignore
/// with_canonical_log(|log| log.team_id = Some(123));
/// with_canonical_log(|log| log.property_cache_hits += 1);
/// ```
pub fn with_canonical_log(f: impl FnOnce(&mut FlagsCanonicalLogLine)) {
    let _ = CANONICAL_LOG.try_with(|log| f(&mut log.borrow_mut()));
}

/// Run an async block with a canonical log in scope.
/// Returns both the result and the final log state.
///
/// The log is automatically available to all code within the async block
/// via `with_canonical_log()`.
///
/// # Example
/// ```ignore
/// let log = FlagsCanonicalLogLine::new(request_id, ip);
/// let (result, log) = run_with_canonical_log(log, async {
///     // Code here can use with_canonical_log() to modify the log
///     process_request().await
/// }).await;
/// log.emit();
/// ```
pub async fn run_with_canonical_log<F, T>(
    log: FlagsCanonicalLogLine,
    f: F,
) -> (T, FlagsCanonicalLogLine)
where
    F: Future<Output = T>,
{
    CANONICAL_LOG
        .scope(RefCell::new(log), async {
            let result = f.await;
            let log = CANONICAL_LOG.with(|l| l.take());
            (result, log)
        })
        .await
}

/// Truncate a string to a maximum number of characters (not bytes).
fn truncate_chars(s: &str, max_chars: usize) -> String {
    s.chars().take(max_chars).collect()
}

/// Accumulates data throughout a /flags request lifecycle for canonical logging.
///
/// A canonical log line is a single comprehensive log entry emitted at request
/// completion containing all key telemetry. This enables simple ClickHouse queries
/// for debugging without needing to join multiple log entries.
///
/// Access and modify via `with_canonical_log()` from anywhere in the async task.
#[derive(Debug, Clone)]
pub struct FlagsCanonicalLogLine {
    // Request identification
    pub request_id: Uuid,
    pub ip: String,
    pub start_time: Instant,

    // Request metadata (useful for SDK debugging)
    pub user_agent: Option<String>,
    pub lib: Option<&'static str>,
    pub lib_version: Option<String>,
    pub api_version: Option<String>,

    // Populated during authentication
    pub team_id: Option<i32>,
    pub distinct_id: Option<String>,

    // Populated during flag evaluation
    pub flags_evaluated: usize,
    pub flags_experience_continuity: usize,
    pub flags_disabled: bool,
    pub quota_limited: bool,

    // Deep evaluation metrics (populated via task_local from flag_matching.rs)
    pub db_property_fetches: usize,
    pub property_cache_hits: usize,
    pub property_cache_misses: usize,
    pub cohorts_evaluated: usize,
    pub flags_errored: usize,
    pub hash_key_override_attempted: bool,
    pub hash_key_override_succeeded: bool,

    // Rate limiting
    pub rate_limited: bool,

    // Outcome (populated at response time)
    pub http_status: u16,
    pub error_code: Option<String>,
}

impl Default for FlagsCanonicalLogLine {
    fn default() -> Self {
        Self {
            request_id: Uuid::nil(),
            ip: String::new(),
            start_time: Instant::now(),
            user_agent: None,
            lib: None,
            lib_version: None,
            api_version: None,
            team_id: None,
            distinct_id: None,
            flags_evaluated: 0,
            flags_experience_continuity: 0,
            flags_disabled: false,
            quota_limited: false,
            db_property_fetches: 0,
            property_cache_hits: 0,
            property_cache_misses: 0,
            cohorts_evaluated: 0,
            flags_errored: 0,
            hash_key_override_attempted: false,
            hash_key_override_succeeded: false,
            rate_limited: false,
            http_status: 200,
            error_code: None,
        }
    }
}

impl FlagsCanonicalLogLine {
    pub fn new(request_id: Uuid, ip: String) -> Self {
        Self {
            request_id,
            ip,
            ..Default::default()
        }
    }

    /// Emit the canonical log line. Call once at request completion.
    pub fn emit(&self) {
        let duration_ms = self.start_time.elapsed().as_millis() as u64;

        // Truncate user_agent to prevent log bloat from very long headers (some bots send KB+).
        // Note: distinct_id is already truncated at request parsing time (see MAX_DISTINCT_ID_LEN).
        let user_agent = self.user_agent.as_ref().map(|ua| truncate_chars(ua, 512));

        tracing::info!(
            request_id = %self.request_id,
            team_id = ?self.team_id,
            distinct_id = ?self.distinct_id,
            ip = %self.ip,
            user_agent = ?user_agent,
            lib = ?self.lib,
            lib_version = ?self.lib_version,
            api_version = ?self.api_version,
            duration_ms = duration_ms,
            http_status = self.http_status,
            flags_evaluated = self.flags_evaluated,
            flags_experience_continuity = self.flags_experience_continuity,
            flags_disabled = self.flags_disabled,
            quota_limited = self.quota_limited,
            db_property_fetches = self.db_property_fetches,
            property_cache_hits = self.property_cache_hits,
            property_cache_misses = self.property_cache_misses,
            cohorts_evaluated = self.cohorts_evaluated,
            flags_errored = self.flags_errored,
            hash_key_override_attempted = self.hash_key_override_attempted,
            hash_key_override_succeeded = self.hash_key_override_succeeded,
            rate_limited = self.rate_limited,
            error_code = ?self.error_code,
            "canonical_log_line"
        );
    }

    /// Populate error fields from a FlagError without emitting.
    pub fn set_error(&mut self, error: &FlagError) {
        self.http_status = error.status_code();
        self.error_code = Some(error.error_code().to_string());
    }

    /// Populate error fields from a FlagError and emit the log line.
    pub fn emit_for_error(&mut self, error: &FlagError) {
        self.set_error(error);
        self.emit();
    }
}

/// Set error on the task-local canonical log if in scope.
pub fn set_canonical_log_error(error: &FlagError) {
    with_canonical_log(|log| log.set_error(error));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_creates_with_defaults() {
        let request_id = Uuid::new_v4();
        let log = FlagsCanonicalLogLine::new(request_id, "192.168.1.1".to_string());

        assert_eq!(log.request_id, request_id);
        assert_eq!(log.ip, "192.168.1.1");
        assert!(log.user_agent.is_none());
        assert!(log.lib.is_none());
        assert!(log.lib_version.is_none());
        assert!(log.api_version.is_none());
        assert!(log.team_id.is_none());
        assert!(log.distinct_id.is_none());
        assert_eq!(log.flags_evaluated, 0);
        assert_eq!(log.flags_experience_continuity, 0);
        assert!(!log.flags_disabled);
        assert!(!log.quota_limited);
        assert_eq!(log.db_property_fetches, 0);
        assert_eq!(log.property_cache_hits, 0);
        assert_eq!(log.property_cache_misses, 0);
        assert_eq!(log.cohorts_evaluated, 0);
        assert_eq!(log.flags_errored, 0);
        assert!(!log.hash_key_override_attempted);
        assert!(!log.hash_key_override_succeeded);
        assert!(!log.rate_limited);
        assert_eq!(log.http_status, 200);
        assert!(log.error_code.is_none());
    }

    #[test]
    fn test_emit_does_not_panic() {
        let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.emit();
    }

    #[test]
    fn test_emit_with_all_fields_populated() {
        let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.user_agent = Some("posthog-python/1.0.0".to_string());
        log.lib = Some("posthog-python");
        log.lib_version = Some("1.0.0".to_string());
        log.api_version = Some("3".to_string());
        log.team_id = Some(123);
        log.distinct_id = Some("user_abc".to_string());
        log.flags_evaluated = 10;
        log.flags_experience_continuity = 2;
        log.flags_disabled = false;
        log.quota_limited = true;
        log.db_property_fetches = 3;
        log.property_cache_hits = 5;
        log.property_cache_misses = 2;
        log.cohorts_evaluated = 4;
        log.flags_errored = 1;
        log.hash_key_override_attempted = true;
        log.hash_key_override_succeeded = true;
        log.rate_limited = false;
        log.http_status = 200;
        log.emit();
    }

    #[test]
    fn test_emit_with_error() {
        let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.http_status = 429;
        log.rate_limited = true;
        log.error_code = Some("rate_limited".to_string());
        log.emit();
    }

    #[test]
    fn test_with_canonical_log_no_ops_outside_scope() {
        // Should not panic when called outside a scope
        with_canonical_log(|log| log.team_id = Some(123));
    }

    #[tokio::test]
    async fn test_run_with_canonical_log_provides_access() {
        let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());

        let (result, final_log) = run_with_canonical_log(log, async {
            with_canonical_log(|l| l.team_id = Some(456));
            with_canonical_log(|l| l.flags_evaluated = 10);
            with_canonical_log(|l| l.property_cache_hits += 1);
            with_canonical_log(|l| l.property_cache_hits += 1);
            "done"
        })
        .await;

        assert_eq!(result, "done");
        assert_eq!(final_log.team_id, Some(456));
        assert_eq!(final_log.flags_evaluated, 10);
        assert_eq!(final_log.property_cache_hits, 2);
    }

    #[tokio::test]
    async fn test_run_with_canonical_log_returns_modified_log() {
        let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());

        let (_, final_log) = run_with_canonical_log(log, async {
            with_canonical_log(|l| {
                l.db_property_fetches = 3;
                l.cohorts_evaluated = 5;
                l.hash_key_override_attempted = true;
                l.hash_key_override_succeeded = true;
            });
        })
        .await;

        assert_eq!(final_log.db_property_fetches, 3);
        assert_eq!(final_log.cohorts_evaluated, 5);
        assert!(final_log.hash_key_override_attempted);
        assert!(final_log.hash_key_override_succeeded);
    }

    #[test]
    fn test_clone_preserves_all_fields() {
        let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.user_agent = Some("posthog-python/1.0.0".to_string());
        log.lib = Some("posthog-python");
        log.lib_version = Some("1.0.0".to_string());
        log.api_version = Some("3".to_string());
        log.team_id = Some(123);
        log.distinct_id = Some("user123".to_string());
        log.flags_evaluated = 5;
        log.flags_experience_continuity = 1;
        log.flags_disabled = true;
        log.quota_limited = true;
        log.db_property_fetches = 2;
        log.property_cache_hits = 3;
        log.property_cache_misses = 1;
        log.cohorts_evaluated = 4;
        log.flags_errored = 2;
        log.hash_key_override_attempted = true;
        log.hash_key_override_succeeded = false;
        log.rate_limited = true;
        log.http_status = 429;
        log.error_code = Some("rate_limited".to_string());

        let cloned = log.clone();

        assert_eq!(cloned.request_id, log.request_id);
        assert_eq!(cloned.ip, log.ip);
        assert_eq!(cloned.user_agent, log.user_agent);
        assert_eq!(cloned.lib, log.lib);
        assert_eq!(cloned.lib_version, log.lib_version);
        assert_eq!(cloned.api_version, log.api_version);
        assert_eq!(cloned.team_id, log.team_id);
        assert_eq!(cloned.distinct_id, log.distinct_id);
        assert_eq!(cloned.flags_evaluated, log.flags_evaluated);
        assert_eq!(
            cloned.flags_experience_continuity,
            log.flags_experience_continuity
        );
        assert_eq!(cloned.flags_disabled, log.flags_disabled);
        assert_eq!(cloned.quota_limited, log.quota_limited);
        assert_eq!(cloned.db_property_fetches, log.db_property_fetches);
        assert_eq!(cloned.property_cache_hits, log.property_cache_hits);
        assert_eq!(cloned.property_cache_misses, log.property_cache_misses);
        assert_eq!(cloned.cohorts_evaluated, log.cohorts_evaluated);
        assert_eq!(cloned.flags_errored, log.flags_errored);
        assert_eq!(
            cloned.hash_key_override_attempted,
            log.hash_key_override_attempted
        );
        assert_eq!(
            cloned.hash_key_override_succeeded,
            log.hash_key_override_succeeded
        );
        assert_eq!(cloned.rate_limited, log.rate_limited);
        assert_eq!(cloned.http_status, log.http_status);
        assert_eq!(cloned.error_code, log.error_code);
    }
}
