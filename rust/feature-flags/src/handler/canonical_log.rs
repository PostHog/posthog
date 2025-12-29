use crate::api::errors::FlagError;
use std::time::Instant;
use uuid::Uuid;

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
/// Created at request start, populated during processing, emitted at request end.
///
/// Use [`CanonicalLogGuard`] to ensure the log is always emitted, even on early returns.
#[derive(Debug, Clone)]
pub struct CanonicalLogLine {
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
    pub flags_evaluated: Option<usize>,
    pub flags_enabled: Option<usize>,
    pub flags_disabled: bool,
    pub quota_limited: bool,

    // Rate limiting
    pub rate_limited: bool,

    // Outcome (populated at response time)
    pub http_status: u16,
    pub error_code: Option<String>,
}

impl Default for CanonicalLogLine {
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
            flags_evaluated: None,
            flags_enabled: None,
            flags_disabled: false,
            quota_limited: false,
            rate_limited: false,
            http_status: 200,
            error_code: None,
        }
    }
}

impl CanonicalLogLine {
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

        // Truncate distinct_id to prevent log line explosion from long IDs.
        let distinct_id = self.distinct_id.as_ref().map(|d| truncate_chars(d, 64));

        // Truncate user_agent to prevent log bloat from very long headers (some bots send KB+).
        let user_agent = self.user_agent.as_ref().map(|ua| truncate_chars(ua, 512));

        tracing::info!(
            request_id = %self.request_id,
            team_id = ?self.team_id,
            distinct_id = ?distinct_id,
            ip = %self.ip,
            user_agent = ?user_agent,
            lib = ?self.lib,
            lib_version = ?self.lib_version,
            api_version = ?self.api_version,
            duration_ms = duration_ms,
            http_status = self.http_status,
            flags_evaluated = ?self.flags_evaluated,
            flags_enabled = ?self.flags_enabled,
            flags_disabled = self.flags_disabled,
            quota_limited = self.quota_limited,
            rate_limited = self.rate_limited,
            error_code = ?self.error_code,
            "canonical_log_line"
        );
    }

    /// Populate error fields from a FlagError without emitting.
    ///
    /// Use this when the guard will emit on drop (e.g., early returns).
    pub fn set_error(&mut self, error: &FlagError) {
        self.http_status = error.status_code();
        self.error_code = Some(error.error_code().to_string());
    }

    /// Populate error fields from a FlagError and emit the log line.
    ///
    /// Use this when manually managing the log (after `into_inner()`).
    pub fn emit_for_error(&mut self, error: &FlagError) {
        self.set_error(error);
        self.emit();
    }
}

/// RAII guard that ensures the canonical log line is always emitted.
///
/// When the guard is dropped (goes out of scope), it automatically emits the log.
/// This prevents silent data loss if new error paths are added without explicit emit() calls.
///
/// # Example
/// ```ignore
/// let guard = CanonicalLogGuard::new(CanonicalLogLine {
///     request_id,
///     ip: ip_string,
///     user_agent: Some("posthog-python/3.0.0".to_string()),
///     ..Default::default()
/// });
/// guard.log_mut().team_id = Some(123);  // Fields discovered during processing
/// // Log is automatically emitted when guard goes out of scope
/// ```
pub struct CanonicalLogGuard {
    log: CanonicalLogLine,
    emitted: bool,
}

impl CanonicalLogGuard {
    pub fn new(log: CanonicalLogLine) -> Self {
        Self {
            log,
            emitted: false,
        }
    }

    /// Get a mutable reference to the underlying log line for populating fields.
    pub fn log_mut(&mut self) -> &mut CanonicalLogLine {
        &mut self.log
    }

    /// Get an immutable reference to the underlying log line.
    pub fn log(&self) -> &CanonicalLogLine {
        &self.log
    }

    /// Consume the guard and return the inner log line without emitting.
    /// Use this when you need to pass the log through async boundaries.
    pub fn into_inner(mut self) -> CanonicalLogLine {
        self.emitted = true; // Prevent double emission
        std::mem::take(&mut self.log)
    }

    /// Explicitly emit the log and mark as emitted to prevent double emission on drop.
    pub fn emit(mut self) {
        self.log.emit();
        self.emitted = true;
    }
}

impl Drop for CanonicalLogGuard {
    fn drop(&mut self) {
        if !self.emitted {
            self.log.emit();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_creates_with_defaults() {
        let request_id = Uuid::new_v4();
        let log = CanonicalLogLine::new(request_id, "192.168.1.1".to_string());

        assert_eq!(log.request_id, request_id);
        assert_eq!(log.ip, "192.168.1.1");
        assert!(log.user_agent.is_none());
        assert!(log.lib.is_none());
        assert!(log.lib_version.is_none());
        assert!(log.api_version.is_none());
        assert!(log.team_id.is_none());
        assert!(log.distinct_id.is_none());
        assert!(log.flags_evaluated.is_none());
        assert!(log.flags_enabled.is_none());
        assert!(!log.flags_disabled);
        assert!(!log.quota_limited);
        assert!(!log.rate_limited);
        assert_eq!(log.http_status, 200);
        assert!(log.error_code.is_none());
    }

    #[test]
    fn test_emit_does_not_panic() {
        let log = CanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        // Should not panic
        log.emit();
    }

    #[test]
    fn test_emit_with_all_fields_populated() {
        let mut log = CanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.user_agent = Some("posthog-python/1.0.0".to_string());
        log.lib = Some("posthog-python");
        log.lib_version = Some("1.0.0".to_string());
        log.api_version = Some("3".to_string());
        log.team_id = Some(123);
        log.distinct_id = Some("user_abc".to_string());
        log.flags_evaluated = Some(10);
        log.flags_enabled = Some(5);
        log.flags_disabled = false;
        log.quota_limited = true;
        log.rate_limited = false;
        log.http_status = 200;
        // Should not panic
        log.emit();
    }

    #[test]
    fn test_emit_with_error() {
        let mut log = CanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.http_status = 429;
        log.rate_limited = true;
        log.error_code = Some("rate_limited".to_string());
        // Should not panic
        log.emit();
    }

    #[test]
    fn test_long_distinct_id_is_truncated_in_emit() {
        let mut log = CanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        // Create a distinct_id longer than 64 characters
        log.distinct_id = Some("a".repeat(100));
        // Should not panic - truncation happens in emit()
        log.emit();
    }

    #[test]
    fn test_multibyte_distinct_id_truncation() {
        let mut log = CanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        // Create a distinct_id with multi-byte characters (emoji) longer than 64 chars
        // Each emoji is 4 bytes but counts as 1 character
        log.distinct_id = Some("🎉".repeat(100));
        // Should not panic and should truncate by character count, not byte count
        log.emit();
    }

    fn test_log() -> CanonicalLogLine {
        CanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string())
    }

    #[test]
    fn test_guard_emits_on_drop() {
        // We can't easily verify the log was emitted, but we can verify no panic
        let guard = CanonicalLogGuard::new(test_log());
        drop(guard);
        // If we get here, the guard emitted successfully on drop
    }

    #[test]
    fn test_guard_log_mut_allows_modification() {
        let mut guard = CanonicalLogGuard::new(test_log());
        guard.log_mut().team_id = Some(123);
        guard.log_mut().http_status = 200;
        assert_eq!(guard.log().team_id, Some(123));
        assert_eq!(guard.log().http_status, 200);
    }

    #[test]
    fn test_guard_explicit_emit_prevents_double_emission() {
        let mut guard = CanonicalLogGuard::new(test_log());
        guard.log_mut().http_status = 200;
        guard.emit(); // Explicit emit
                      // Guard is consumed, so no double emission on drop
    }

    #[test]
    fn test_guard_into_inner_prevents_emission() {
        let mut guard = CanonicalLogGuard::new(test_log());
        guard.log_mut().team_id = Some(456);
        let log = guard.into_inner();
        // Guard is consumed without emitting, log can be used elsewhere
        assert_eq!(log.team_id, Some(456));
    }

    #[test]
    fn test_clone_preserves_all_fields() {
        let mut log = CanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.user_agent = Some("posthog-python/1.0.0".to_string());
        log.lib = Some("posthog-python");
        log.lib_version = Some("1.0.0".to_string());
        log.api_version = Some("3".to_string());
        log.team_id = Some(123);
        log.distinct_id = Some("user123".to_string());
        log.flags_evaluated = Some(5);
        log.flags_enabled = Some(3);
        log.flags_disabled = true;
        log.quota_limited = true;
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
        assert_eq!(cloned.flags_enabled, log.flags_enabled);
        assert_eq!(cloned.flags_disabled, log.flags_disabled);
        assert_eq!(cloned.quota_limited, log.quota_limited);
        assert_eq!(cloned.rate_limited, log.rate_limited);
        assert_eq!(cloned.http_status, log.http_status);
        assert_eq!(cloned.error_code, log.error_code);
    }
}
