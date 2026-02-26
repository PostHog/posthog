use crate::api::errors::FlagError;
use crate::metrics::consts::FLAG_DB_OPERATIONS_PER_REQUEST;
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

// Thread-local fallback for rayon worker threads.
// Rayon threads don't have access to tokio task-locals, so we use a
// std::thread_local to capture evaluation counters during parallel flag
// evaluation. The counters are then merged back into the request's
// canonical log on the tokio side after rayon returns.
std::thread_local! {
    static RAYON_CANONICAL_LOG: RefCell<Option<FlagsCanonicalLogLine>> = const { RefCell::new(None) };
}

/// Safely modify the canonical log if one exists in scope.
/// No-ops silently if called outside a canonical log scope.
///
/// Tries the tokio task-local first (normal async request path), then
/// falls back to the std::thread_local (rayon parallel-eval path).
///
/// # Example
/// ```ignore
/// with_canonical_log(|log| log.team_id = Some(123));
/// with_canonical_log(|log| log.property_cache_hits += 1);
/// ```
pub fn with_canonical_log(f: impl FnOnce(&mut FlagsCanonicalLogLine)) {
    // Probe whether the tokio task-local is accessible without consuming `f`.
    // On rayon threads there is no tokio task context, so this returns Err.
    if CANONICAL_LOG.try_with(|_| ()).is_ok() {
        CANONICAL_LOG.with(|log| f(&mut log.borrow_mut()));
    } else {
        RAYON_CANONICAL_LOG.with(|cell| {
            if let Some(ref mut log) = *cell.borrow_mut() {
                f(log);
            }
        });
    }
}

#[must_use = "guard cleans up the thread-local on drop; dropping immediately is a no-op"]
pub(crate) struct RayonCanonicalLogGuard;

impl Drop for RayonCanonicalLogGuard {
    fn drop(&mut self) {
        drop(take_rayon_canonical_log());
    }
}

/// Install a fresh canonical log on the current thread for rayon evaluation.
/// Returns an RAII guard that clears the thread-local on drop, ensuring
/// cleanup even if the evaluation panics. Call [`take_rayon_canonical_log`]
/// before the guard is dropped to retrieve the accumulated counters.
pub(crate) fn install_rayon_canonical_log() -> RayonCanonicalLogGuard {
    RAYON_CANONICAL_LOG.with(|cell| {
        *cell.borrow_mut() = Some(FlagsCanonicalLogLine::default());
    });

    RayonCanonicalLogGuard
}

/// Take the accumulated canonical log from the current rayon thread.
/// Returns `None` if no log was installed.
pub(crate) fn take_rayon_canonical_log() -> Option<FlagsCanonicalLogLine> {
    RAYON_CANONICAL_LOG.with(|cell| cell.borrow_mut().take())
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
/// Handles multibyte UTF-8 characters correctly.
fn truncate_chars(s: &str, max_chars: usize) -> &str {
    match s.char_indices().nth(max_chars) {
        Some((byte_idx, _)) => &s[..byte_idx],
        None => s,
    }
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
    pub device_id: Option<String>,
    /// The anonymous distinct ID sent with the request for experience continuity.
    pub anon_distinct_id: Option<String>,

    // Populated during flag evaluation
    pub flags_evaluated: usize,
    pub flags_experience_continuity: usize,
    /// Number of flags that used device_id for bucketing (instead of distinct_id).
    pub flags_device_id_bucketing: usize,
    pub flags_disabled: bool,
    pub quota_limited: bool,
    /// Source of the flags data: "Redis", "S3", or "Fallback" (PostgreSQL).
    pub flags_cache_source: Option<&'static str>,

    // Deep evaluation metrics (populated via task_local from flag_matching.rs)
    /// Total number of database property fetch operations (aggregate counter).
    pub db_property_fetches: usize,
    /// Number of person property queries made to the database.
    pub person_queries: usize,
    /// Number of group property queries made to the database.
    pub group_queries: usize,
    /// Number of static cohort membership queries made to the database.
    pub static_cohort_queries: usize,
    /// Time spent on person property queries in milliseconds.
    pub person_query_time_ms: u64,
    /// Time spent on group property queries in milliseconds.
    pub group_query_time_ms: u64,
    /// Time spent on static cohort membership queries in milliseconds.
    pub cohort_query_time_ms: u64,
    pub property_cache_hits: usize,
    pub property_cache_misses: usize,
    /// True if person properties were not found in evaluation state cache.
    pub person_properties_not_cached: bool,
    /// True if group properties were not found in evaluation state cache.
    pub group_properties_not_cached: bool,
    pub cohorts_evaluated: usize,
    pub flags_errored: usize,
    /// Number of errors encountered during dependency graph construction.
    /// These errors (like missing dependencies or cycles) set errors_while_computing_flags=true
    /// in the response but don't increment flags_errored.
    pub dependency_graph_errors: usize,
    /// Status of hash key override lookup for experience continuity.
    /// Values:
    /// - None: no flags require experience continuity
    /// - "skipped": optimization applied (100% rollout, no variants needing lookup)
    /// - "error": query failed
    /// - "empty": query succeeded, no overrides found
    /// - "found": query succeeded, overrides returned
    pub hash_key_override_status: Option<&'static str>,

    // Rate limiting
    pub rate_limited: bool,

    // Cache sources (populated during data fetching)
    /// Where team metadata was fetched from: "redis", "s3", "fallback", or None if not fetched
    pub team_cache_source: Option<&'static str>,

    // Outcome (populated at response time)
    pub http_status: u16,
    /// Error code from FlagError::error_code(). Uses &'static str to avoid allocation.
    pub error_code: Option<&'static str>,
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
            device_id: None,
            anon_distinct_id: None,
            flags_evaluated: 0,
            flags_experience_continuity: 0,
            flags_device_id_bucketing: 0,
            flags_disabled: false,
            quota_limited: false,
            flags_cache_source: None,
            db_property_fetches: 0,
            person_queries: 0,
            group_queries: 0,
            static_cohort_queries: 0,
            person_query_time_ms: 0,
            group_query_time_ms: 0,
            cohort_query_time_ms: 0,
            property_cache_hits: 0,
            property_cache_misses: 0,
            person_properties_not_cached: false,
            group_properties_not_cached: false,
            cohorts_evaluated: 0,
            flags_errored: 0,
            dependency_graph_errors: 0,
            hash_key_override_status: None,
            rate_limited: false,
            team_cache_source: None,
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
        let user_agent = self.user_agent.as_deref().map(|ua| truncate_chars(ua, 512));

        tracing::info!(
            request_id = %self.request_id,
            team_id = self.team_id,
            distinct_id = self.distinct_id.as_deref(),
            device_id = self.device_id.as_deref(),
            anon_distinct_id = self.anon_distinct_id.as_deref(),
            ip = %self.ip,
            user_agent = user_agent,
            lib = self.lib,
            lib_version = self.lib_version.as_deref(),
            api_version = self.api_version.as_deref(),
            duration_ms = duration_ms,
            http_status = self.http_status,
            flags_evaluated = self.flags_evaluated,
            flags_experience_continuity = self.flags_experience_continuity,
            flags_device_id_bucketing = self.flags_device_id_bucketing,
            flags_disabled = self.flags_disabled,
            quota_limited = self.quota_limited,
            flags_cache_source = self.flags_cache_source,
            db_property_fetches = self.db_property_fetches,
            person_queries = self.person_queries,
            group_queries = self.group_queries,
            static_cohort_queries = self.static_cohort_queries,
            person_query_time_ms = self.person_query_time_ms,
            group_query_time_ms = self.group_query_time_ms,
            cohort_query_time_ms = self.cohort_query_time_ms,
            property_cache_hits = self.property_cache_hits,
            property_cache_misses = self.property_cache_misses,
            person_properties_not_cached = self.person_properties_not_cached,
            group_properties_not_cached = self.group_properties_not_cached,
            cohorts_evaluated = self.cohorts_evaluated,
            flags_errored = self.flags_errored,
            dependency_graph_errors = self.dependency_graph_errors,
            hash_key_override_status = self.hash_key_override_status,
            rate_limited = self.rate_limited,
            team_cache_source = self.team_cache_source,
            error_code = self.error_code,
            "canonical_log_line"
        );
    }

    /// Emit DB operations metrics for observability.
    /// This emits a histogram for each operation type with the count of operations.
    /// Labels: team_id, operation_type
    pub fn emit_db_operations_metrics(&self) {
        let team_id = self
            .team_id
            .map(|id| id.to_string())
            .unwrap_or_else(|| "unknown".to_string());

        // Emit person query count
        if self.person_queries > 0 {
            common_metrics::histogram(
                FLAG_DB_OPERATIONS_PER_REQUEST,
                &[
                    ("team_id".to_string(), team_id.clone()),
                    ("operation_type".to_string(), "person_query".to_string()),
                ],
                self.person_queries as f64,
            );
        }

        // Emit group query count
        if self.group_queries > 0 {
            common_metrics::histogram(
                FLAG_DB_OPERATIONS_PER_REQUEST,
                &[
                    ("team_id".to_string(), team_id.clone()),
                    ("operation_type".to_string(), "group_query".to_string()),
                ],
                self.group_queries as f64,
            );
        }

        // Emit static cohort query count
        if self.static_cohort_queries > 0 {
            common_metrics::histogram(
                FLAG_DB_OPERATIONS_PER_REQUEST,
                &[
                    ("team_id".to_string(), team_id.clone()),
                    ("operation_type".to_string(), "cohort_query".to_string()),
                ],
                self.static_cohort_queries as f64,
            );
        }
    }

    /// Merge evaluation counters accumulated on a rayon thread back into this log.
    ///
    /// Only merges fields that are written during per-flag evaluation inside
    /// `evaluate_single_flag` and its callees. Request-level metadata (request_id,
    /// team_id, ip, etc.) is intentionally not merged.
    ///
    /// `flags_errored` is excluded because it is incremented in `process_flag_result`,
    /// which runs on the tokio task after rayon returns.
    ///
    /// Numeric counters are summed; boolean flags are OR'd.
    ///
    // TODO: consider splitting these eval counters into an `EvalCounters` sub-struct
    // so that new counters are merged automatically and this field list doesn't drift.
    // See https://github.com/PostHog/posthog/issues/49255
    pub fn merge_rayon_delta(&mut self, delta: &FlagsCanonicalLogLine) {
        self.flags_device_id_bucketing += delta.flags_device_id_bucketing;
        self.cohorts_evaluated += delta.cohorts_evaluated;
        self.property_cache_hits += delta.property_cache_hits;
        self.property_cache_misses += delta.property_cache_misses;
        self.person_properties_not_cached |= delta.person_properties_not_cached;
        self.group_properties_not_cached |= delta.group_properties_not_cached;
    }

    /// Populate error fields from a FlagError without emitting.
    pub fn set_error(&mut self, error: &FlagError) {
        self.http_status = error.status_code();
        self.error_code = Some(error.error_code());
    }

    /// Populate error fields from a FlagError and emit the log line.
    pub fn emit_for_error(&mut self, error: &FlagError) {
        self.set_error(error);
        self.emit();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::errors::{ClientFacingError, FlagError};
    use crate::utils::graph_utils::DependencyType;

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
        assert!(log.device_id.is_none());
        assert!(log.anon_distinct_id.is_none());
        assert_eq!(log.flags_evaluated, 0);
        assert_eq!(log.flags_experience_continuity, 0);
        assert_eq!(log.flags_device_id_bucketing, 0);
        assert!(!log.flags_disabled);
        assert!(!log.quota_limited);
        assert!(log.flags_cache_source.is_none());
        assert_eq!(log.db_property_fetches, 0);
        assert_eq!(log.person_queries, 0);
        assert_eq!(log.group_queries, 0);
        assert_eq!(log.static_cohort_queries, 0);
        assert_eq!(log.property_cache_hits, 0);
        assert_eq!(log.property_cache_misses, 0);
        assert!(!log.person_properties_not_cached);
        assert!(!log.group_properties_not_cached);
        assert_eq!(log.cohorts_evaluated, 0);
        assert_eq!(log.flags_errored, 0);
        assert_eq!(log.dependency_graph_errors, 0);
        assert!(log.hash_key_override_status.is_none());
        assert!(!log.rate_limited);
        assert!(log.team_cache_source.is_none());
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
        log.device_id = Some("device_123".to_string());
        log.flags_evaluated = 10;
        log.flags_experience_continuity = 2;
        log.flags_device_id_bucketing = 3;
        log.flags_disabled = false;
        log.quota_limited = true;
        log.flags_cache_source = Some("redis");
        log.db_property_fetches = 3;
        log.property_cache_hits = 5;
        log.property_cache_misses = 2;
        log.cohorts_evaluated = 4;
        log.flags_errored = 1;
        log.hash_key_override_status = Some("found");
        log.rate_limited = false;
        log.team_cache_source = Some("redis");
        log.http_status = 200;
        log.emit();
    }

    #[test]
    fn test_emit_with_error() {
        let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.http_status = 429;
        log.rate_limited = true;
        log.error_code = Some("rate_limited");
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
                l.hash_key_override_status = Some("found");
            });
        })
        .await;

        assert_eq!(final_log.db_property_fetches, 3);
        assert_eq!(final_log.cohorts_evaluated, 5);
        assert_eq!(final_log.hash_key_override_status, Some("found"));
    }

    #[tokio::test]
    async fn test_dependency_graph_errors_is_tracked() {
        let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());

        let graph_errors_count = 2;
        let (_, final_log) = run_with_canonical_log(log, async {
            with_canonical_log(|l| l.dependency_graph_errors = graph_errors_count);
        })
        .await;

        assert_eq!(
            final_log.dependency_graph_errors, graph_errors_count,
            "dependency_graph_errors should track the count of graph construction errors"
        );
    }

    #[test]
    fn test_clone_creates_independent_copy() {
        // Clone correctness is compiler-verified via #[derive(Clone)].
        // This test verifies clone creates an independent copy.
        let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
        log.team_id = Some(123);

        let mut cloned = log.clone();
        cloned.team_id = Some(456);

        // Ensure original is unmodified
        assert_eq!(log.team_id, Some(123));
        assert_eq!(cloned.team_id, Some(456));
    }

    mod task_local_isolation_tests {
        use super::*;

        #[tokio::test]
        async fn test_concurrent_requests_are_isolated() {
            // Spawn multiple concurrent tasks that each modify their own canonical log.
            // Verify that modifications in one task don't affect other tasks.
            let handles: Vec<_> = (0..10)
                .map(|i| {
                    tokio::spawn(async move {
                        let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), format!("10.0.0.{i}"));

                        let (_, final_log) = run_with_canonical_log(log, async {
                            // Each task sets its own unique team_id
                            with_canonical_log(|l| l.team_id = Some(i as i32));
                            with_canonical_log(|l| l.flags_evaluated = i);

                            // Small delay to allow interleaving
                            tokio::task::yield_now().await;

                            // Update more fields after yield
                            with_canonical_log(|l| l.property_cache_hits = i * 2);
                        })
                        .await;

                        // Return the final values for verification
                        (
                            i,
                            final_log.team_id,
                            final_log.flags_evaluated,
                            final_log.property_cache_hits,
                        )
                    })
                })
                .collect();

            // Verify each task got its own isolated log
            for handle in handles {
                let (i, team_id, flags_evaluated, cache_hits) = handle.await.unwrap();
                assert_eq!(team_id, Some(i as i32), "team_id should match task index");
                assert_eq!(
                    flags_evaluated, i,
                    "flags_evaluated should match task index"
                );
                assert_eq!(
                    cache_hits,
                    i * 2,
                    "property_cache_hits should match task index * 2"
                );
            }
        }

        #[tokio::test]
        async fn test_nested_scopes_are_independent() {
            // Test that we can't accidentally nest canonical log scopes
            // (each run_with_canonical_log creates a new scope)
            let outer_log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "outer".to_string());

            let (_, outer_final) = run_with_canonical_log(outer_log, async {
                with_canonical_log(|l| l.team_id = Some(1));

                // Start a nested scope with different values
                let inner_log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "inner".to_string());
                let (_, inner_final) = run_with_canonical_log(inner_log, async {
                    with_canonical_log(|l| l.team_id = Some(2));
                })
                .await;

                // Inner scope should have its own values
                assert_eq!(inner_final.team_id, Some(2));
                assert_eq!(inner_final.ip, "inner");

                // After inner scope ends, we should still be in outer scope
                with_canonical_log(|l| l.flags_evaluated = 100);
            })
            .await;

            // Outer scope should have its own values, unaffected by inner scope
            assert_eq!(outer_final.team_id, Some(1));
            assert_eq!(outer_final.flags_evaluated, 100);
            assert_eq!(outer_final.ip, "outer");
        }

        #[tokio::test]
        async fn test_with_canonical_log_outside_scope_is_safe() {
            // Call with_canonical_log outside any scope - should no-op without panic
            with_canonical_log(|l| l.team_id = Some(999));

            // Now run a proper scope and verify the outside call had no effect
            let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "test".to_string());
            let (_, final_log) = run_with_canonical_log(log, async {
                // Don't modify team_id
            })
            .await;

            assert!(final_log.team_id.is_none());
        }
    }

    mod set_error_tests {
        use super::*;
        use common_cookieless::CookielessManagerError;
        use rstest::rstest;

        #[rstest]
        #[case(FlagError::ClientFacing(ClientFacingError::BadRequest("test".into())), 400, "bad_request")]
        #[case(FlagError::ClientFacing(ClientFacingError::Unauthorized("test".into())), 401, "unauthorized")]
        #[case(
            FlagError::ClientFacing(ClientFacingError::RateLimited),
            429,
            "rate_limited"
        )]
        #[case(
            FlagError::ClientFacing(ClientFacingError::IpRateLimited),
            429,
            "ip_rate_limited"
        )]
        #[case(
            FlagError::ClientFacing(ClientFacingError::TokenRateLimited),
            429,
            "token_rate_limited"
        )]
        #[case(
            FlagError::ClientFacing(ClientFacingError::BillingLimit),
            402,
            "billing_limit"
        )]
        #[case(
            FlagError::ClientFacing(ClientFacingError::ServiceUnavailable),
            503,
            "service_unavailable"
        )]
        #[case(FlagError::Internal("test".into()), 500, "internal_error")]
        #[case(FlagError::RequestDecodingError("test".into()), 400, "request_decoding_error")]
        #[case(FlagError::MissingDistinctId, 400, "missing_distinct_id")]
        #[case(FlagError::NoTokenError, 401, "missing_token")]
        #[case(FlagError::TokenValidationError, 401, "invalid_token")]
        #[case(FlagError::PersonalApiKeyInvalid("test".into()), 401, "personal_api_key_invalid")]
        #[case(FlagError::SecretApiTokenInvalid, 401, "secret_api_token_invalid")]
        #[case(FlagError::NoAuthenticationProvided, 401, "no_authentication")]
        #[case(FlagError::RowNotFound, 500, "row_not_found")]
        #[case(FlagError::DataParsingErrorWithContext("test".into()), 500, "flag_data_parsing_error")]
        #[case(FlagError::DeserializeFiltersError, 500, "deserialize_filters_error")]
        #[case(FlagError::RedisUnavailable, 503, "redis_unavailable")]
        #[case(FlagError::DatabaseUnavailable, 503, "database_unavailable")]
        #[case(FlagError::TimeoutError(None), 503, "timeout")]
        #[case(FlagError::TimeoutError(Some("pool".into())), 503, "timeout")]
        #[case(FlagError::NoGroupTypeMappings, 500, "no_group_type_mappings")]
        #[case(
            FlagError::DependencyNotFound(DependencyType::Flag, 1),
            500,
            "dependency_not_found"
        )]
        #[case(
            FlagError::DependencyCycle(DependencyType::Cohort, 2),
            500,
            "dependency_cycle"
        )]
        #[case(
            FlagError::CohortFiltersParsingError,
            500,
            "cohort_filters_parsing_error"
        )]
        #[case(FlagError::PersonNotFound, 503, "person_not_found")]
        #[case(FlagError::PropertiesNotInCache, 503, "properties_not_in_cache")]
        #[case(
            FlagError::StaticCohortMatchesNotCached,
            503,
            "static_cohort_not_cached"
        )]
        #[case(FlagError::CacheMiss, 503, "cache_miss")]
        #[case(FlagError::DataParsingError, 500, "data_parsing_error")]
        fn test_set_error_populates_fields(
            #[case] error: FlagError,
            #[case] expected_status: u16,
            #[case] expected_code: &'static str,
        ) {
            let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());

            log.set_error(&error);

            assert_eq!(
                log.http_status, expected_status,
                "http_status mismatch for {error:?}"
            );
            assert_eq!(
                log.error_code,
                Some(expected_code),
                "error_code mismatch for {error:?}"
            );
        }

        #[test]
        fn test_set_error_cookieless_bad_request() {
            let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
            let error: FlagError = CookielessManagerError::MissingProperty("test".into()).into();

            log.set_error(&error);

            assert_eq!(log.http_status, 400);
            assert_eq!(log.error_code, Some("cookieless_error"));
        }

        #[test]
        fn test_emit_for_error_sets_error_and_emits() {
            let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
            let error = FlagError::NoTokenError;

            log.emit_for_error(&error);

            // Verify error fields were set (emit_for_error calls set_error internally)
            assert_eq!(log.http_status, 401);
            assert_eq!(log.error_code, Some("missing_token"));
        }
    }

    mod hash_key_override_status_tests {
        use super::*;
        use rstest::rstest;

        #[rstest]
        #[case(None, "no experience continuity flags")]
        #[case(Some("skipped"), "optimization applied - 100% rollout")]
        #[case(Some("error"), "query failed")]
        #[case(Some("empty"), "query succeeded, no overrides")]
        #[case(Some("found"), "query succeeded, overrides returned")]
        fn test_hash_key_override_status_values(
            #[case] status: Option<&'static str>,
            #[case] _description: &str,
        ) {
            let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
            log.hash_key_override_status = status;
            // Verify the value can be set and emit doesn't panic
            assert_eq!(log.hash_key_override_status, status);
            log.emit();
        }

        #[tokio::test]
        async fn test_hash_key_override_status_skipped_in_scope() {
            let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());

            let (_, final_log) = run_with_canonical_log(log, async {
                with_canonical_log(|l| l.hash_key_override_status = Some("skipped"));
            })
            .await;

            assert_eq!(final_log.hash_key_override_status, Some("skipped"));
        }

        #[tokio::test]
        async fn test_hash_key_override_status_error_in_scope() {
            let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());

            let (_, final_log) = run_with_canonical_log(log, async {
                with_canonical_log(|l| l.hash_key_override_status = Some("error"));
            })
            .await;

            assert_eq!(final_log.hash_key_override_status, Some("error"));
        }

        #[tokio::test]
        async fn test_hash_key_override_status_empty_in_scope() {
            let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());

            let (_, final_log) = run_with_canonical_log(log, async {
                with_canonical_log(|l| l.hash_key_override_status = Some("empty"));
            })
            .await;

            assert_eq!(final_log.hash_key_override_status, Some("empty"));
        }
    }

    mod merge_rayon_delta_tests {
        use super::*;
        use rstest::rstest;

        #[rstest]
        // Single delta with all counter fields populated
        #[case(
            &[(3, 5, 10, 2, true, false)],
            3, 5, 10, 2, true, false
        )]
        // Two deltas accumulate: counters sum, booleans OR
        #[case(
            &[(1, 2, 3, 1, false, false), (2, 3, 7, 4, false, true)],
            3, 5, 10, 5, false, true
        )]
        // Empty delta is a no-op
        #[case(
            &[(0, 0, 0, 0, false, false)],
            0, 0, 0, 0, false, false
        )]
        // Boolean fields OR across deltas
        #[case(
            &[(0, 0, 0, 0, true, false), (0, 0, 0, 0, false, true)],
            0, 0, 0, 0, true, true
        )]
        fn test_merge_rayon_delta_from_zero(
            #[case] deltas: &[(usize, usize, usize, usize, bool, bool)],
            #[case] expected_device_id: usize,
            #[case] expected_cohorts: usize,
            #[case] expected_cache_hits: usize,
            #[case] expected_cache_misses: usize,
            #[case] expected_person_not_cached: bool,
            #[case] expected_group_not_cached: bool,
        ) {
            let mut log = FlagsCanonicalLogLine::default();

            for &(device_id, cohorts, hits, misses, person, group) in deltas {
                let delta = FlagsCanonicalLogLine {
                    flags_device_id_bucketing: device_id,
                    cohorts_evaluated: cohorts,
                    property_cache_hits: hits,
                    property_cache_misses: misses,
                    person_properties_not_cached: person,
                    group_properties_not_cached: group,
                    ..Default::default()
                };
                log.merge_rayon_delta(&delta);
            }

            assert_eq!(log.flags_device_id_bucketing, expected_device_id);
            assert_eq!(log.cohorts_evaluated, expected_cohorts);
            assert_eq!(log.property_cache_hits, expected_cache_hits);
            assert_eq!(log.property_cache_misses, expected_cache_misses);
            assert_eq!(log.person_properties_not_cached, expected_person_not_cached);
            assert_eq!(log.group_properties_not_cached, expected_group_not_cached);
        }

        #[test]
        fn test_merge_into_preexisting_counters() {
            let mut log = FlagsCanonicalLogLine {
                property_cache_hits: 10,
                property_cache_misses: 5,
                cohorts_evaluated: 3,
                flags_device_id_bucketing: 2,
                person_properties_not_cached: true,
                group_properties_not_cached: false,
                ..Default::default()
            };

            let delta = FlagsCanonicalLogLine {
                property_cache_hits: 7,
                property_cache_misses: 3,
                cohorts_evaluated: 2,
                flags_device_id_bucketing: 1,
                person_properties_not_cached: false,
                group_properties_not_cached: true,
                ..Default::default()
            };

            log.merge_rayon_delta(&delta);

            assert_eq!(log.property_cache_hits, 17);
            assert_eq!(log.property_cache_misses, 8);
            assert_eq!(log.cohorts_evaluated, 5);
            assert_eq!(log.flags_device_id_bucketing, 3);
            assert!(log.person_properties_not_cached);
            assert!(log.group_properties_not_cached);
        }

        #[test]
        fn test_merge_does_not_touch_request_fields() {
            let mut log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
            log.team_id = Some(123);
            log.flags_evaluated = 50;

            let delta = FlagsCanonicalLogLine {
                team_id: Some(999),
                flags_evaluated: 42,
                property_cache_hits: 5,
                ..Default::default()
            };

            log.merge_rayon_delta(&delta);

            // Request-level fields are unchanged
            assert_eq!(log.team_id, Some(123));
            assert_eq!(log.flags_evaluated, 50);
            // Evaluation counter is merged
            assert_eq!(log.property_cache_hits, 5);
        }
    }

    mod rayon_fallback_tests {
        use super::*;

        #[test]
        fn test_install_and_take_round_trip() {
            let _guard = install_rayon_canonical_log();

            // Modify via with_canonical_log (outside tokio scope, falls back to thread-local)
            with_canonical_log(|log| {
                log.property_cache_hits = 7;
                log.cohorts_evaluated = 3;
            });

            let delta = take_rayon_canonical_log();
            assert!(delta.is_some());
            let delta = delta.unwrap();
            assert_eq!(delta.property_cache_hits, 7);
            assert_eq!(delta.cohorts_evaluated, 3);
        }

        #[test]
        fn test_take_without_install_returns_none() {
            // Ensure clean state
            drop(take_rayon_canonical_log());
            assert!(take_rayon_canonical_log().is_none());
        }

        #[test]
        fn test_take_clears_the_thread_local() {
            let _guard = install_rayon_canonical_log();
            with_canonical_log(|log| log.property_cache_hits = 1);

            let first = take_rayon_canonical_log();
            assert!(first.is_some());

            let second = take_rayon_canonical_log();
            assert!(second.is_none());
        }

        #[test]
        fn test_install_replaces_previous() {
            let _guard = install_rayon_canonical_log();
            with_canonical_log(|log| log.property_cache_hits = 99);

            // Re-install should reset
            let _guard = install_rayon_canonical_log();
            let delta = take_rayon_canonical_log().unwrap();
            assert_eq!(delta.property_cache_hits, 0);
        }

        #[test]
        fn test_guard_cleans_up_on_panic() {
            use std::panic::catch_unwind;

            // Ensure clean state
            drop(take_rayon_canonical_log());

            let result = catch_unwind(|| {
                let _guard = install_rayon_canonical_log();
                with_canonical_log(|log| log.property_cache_hits = 42);
                panic!("simulated evaluation panic");
            });

            assert!(result.is_err(), "should have caught the panic");
            // The guard's Drop should have cleared the thread-local
            assert!(
                take_rayon_canonical_log().is_none(),
                "thread-local should be clean after panic"
            );
        }

        #[test]
        fn test_with_canonical_log_noop_without_either_scope() {
            // Ensure thread-local is clean
            drop(take_rayon_canonical_log());

            // Outside both tokio scope and rayon scope: should no-op without panic
            with_canonical_log(|log| log.team_id = Some(123));
        }

        #[tokio::test]
        async fn test_tokio_scope_takes_precedence_over_thread_local() {
            // Install a rayon thread-local
            let _guard = install_rayon_canonical_log();

            // Run inside a tokio canonical log scope
            let log = FlagsCanonicalLogLine::new(Uuid::new_v4(), "10.0.0.1".to_string());
            let (_, final_log) = run_with_canonical_log(log, async {
                with_canonical_log(|l| l.property_cache_hits = 42);
            })
            .await;

            // The tokio scope should have received the update
            assert_eq!(final_log.property_cache_hits, 42);

            // The rayon thread-local should be untouched
            let rayon_delta = take_rayon_canonical_log().unwrap();
            assert_eq!(rayon_delta.property_cache_hits, 0);
        }

        #[test]
        fn test_rayon_threads_are_isolated() {
            use std::sync::{Arc, Barrier};

            let barrier = Arc::new(Barrier::new(2));
            let (tx1, rx1) = std::sync::mpsc::channel();
            let (tx2, rx2) = std::sync::mpsc::channel();

            let b1 = barrier.clone();
            rayon::spawn(move || {
                let _guard = install_rayon_canonical_log();
                with_canonical_log(|log| log.property_cache_hits = 111);
                b1.wait(); // sync so both threads are alive simultaneously
                let delta = take_rayon_canonical_log().unwrap();
                tx1.send(delta.property_cache_hits).unwrap();
            });

            let b2 = barrier.clone();
            rayon::spawn(move || {
                let _guard = install_rayon_canonical_log();
                with_canonical_log(|log| log.property_cache_hits = 222);
                b2.wait();
                let delta = take_rayon_canonical_log().unwrap();
                tx2.send(delta.property_cache_hits).unwrap();
            });

            assert_eq!(rx1.recv().unwrap(), 111);
            assert_eq!(rx2.recv().unwrap(), 222);
        }
    }

    mod truncate_chars_tests {
        use super::*;
        use rstest::rstest;

        #[rstest]
        #[case("", 10, "")]
        #[case("hello", 10, "hello")]
        #[case("hello", 5, "hello")]
        #[case("hello", 3, "hel")]
        #[case("hello", 0, "")]
        // Multibyte UTF-8: emojis are 4 bytes each but 1 character
        #[case("🎉🎊🎁", 3, "🎉🎊🎁")]
        #[case("🎉🎊🎁", 2, "🎉🎊")]
        #[case("🙂🙂🙂", 2, "🙂🙂")]
        #[case("hello🎉world", 6, "hello🎉")]
        // Mixed ASCII and multibyte
        #[case("café", 4, "café")]
        #[case("café", 3, "caf")]
        #[case("💩abc", 2, "💩a")]
        fn test_truncate_chars(
            #[case] input: &str,
            #[case] max_chars: usize,
            #[case] expected: &str,
        ) {
            assert_eq!(truncate_chars(input, max_chars), expected);
        }

        #[test]
        fn test_truncate_chars_long_input() {
            let long_input = "a".repeat(2000);
            let truncated = truncate_chars(&long_input, 512);
            assert_eq!(truncated.len(), 512);
            assert_eq!(truncated.chars().count(), 512);
        }
    }
}
