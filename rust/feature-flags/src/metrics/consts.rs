// Group type cache metrics
pub const GROUP_TYPE_CACHE_HIT_COUNTER: &str = "flags_group_type_cache_hit_total";
pub const GROUP_TYPE_CACHE_MISS_COUNTER: &str = "flags_group_type_cache_miss_total";
pub const GROUP_TYPE_CACHE_ENTRIES_GAUGE: &str = "flags_group_type_cache_entries";
pub const DB_GROUP_TYPE_READS_COUNTER: &str = "flags_db_group_type_reads_total";
pub const DB_GROUP_TYPE_ERRORS_COUNTER: &str = "flags_db_group_type_errors_total";

// Flag evaluation counters
pub const FLAG_EVALUATION_ERROR_COUNTER: &str = "flags_flag_evaluation_error_total";
pub const FLAG_HASH_KEY_WRITES_COUNTER: &str = "flags_flag_hash_key_writes_total";
pub const FLAG_HASH_KEY_RETRIES_COUNTER: &str = "flags_hash_key_retries_total";
pub const TEAM_CACHE_HIT_COUNTER: &str = "flags_team_cache_hit_total";
pub const DB_TEAM_READS_COUNTER: &str = "flags_db_team_reads_total";
pub const TOKEN_VALIDATION_ERRORS_COUNTER: &str = "flags_token_validation_errors_total";
pub const TEAM_NEGATIVE_CACHE_HIT_COUNTER: &str = "flags_team_negative_cache_hit_total";
pub const PG_TEAM_FALLBACK_SKIPPED_COUNTER: &str = "flags_pg_team_fallback_skipped_total";
pub const DB_COHORT_READS_COUNTER: &str = "flags_db_cohort_reads_total";
pub const DB_COHORT_ERRORS_COUNTER: &str = "flags_db_cohort_errors_total";
pub const COHORT_CACHE_HIT_COUNTER: &str = "flags_cohort_cache_hit_total";
pub const COHORT_CACHE_MISS_COUNTER: &str = "flags_cohort_cache_miss_total";
pub const COHORT_CACHE_SIZE_BYTES_GAUGE: &str = "flags_cohort_cache_size_bytes";
pub const COHORT_CACHE_ENTRIES_GAUGE: &str = "flags_cohort_cache_entries";
// In-memory flag definitions cache (deserialized + regex-compiled).
// Keyed on `(team_id, etag)` where `etag` is the version tag Django writes
// alongside the hypercache payload (`enable_etag=True`). Cache hits avoid the
// payload fetch + deserialization entirely.
pub const FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER: &str =
    "flags_definitions_inmem_cache_hit_total";
pub const FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER: &str =
    "flags_definitions_inmem_cache_miss_total";
pub const FLAG_DEFINITIONS_INMEM_CACHE_SIZE_BYTES_GAUGE: &str =
    "flags_definitions_inmem_cache_size_bytes";
pub const FLAG_DEFINITIONS_INMEM_CACHE_ENTRIES_GAUGE: &str =
    "flags_definitions_inmem_cache_entries";
// Counter for requests that bypassed the version-keyed fast path. Labels are
// mutually exclusive — a bypassing request increments exactly one:
//   reason="sentinel"         — Django wrote `__missing__` (empty team).
//   reason="etag_missing"     — etag key absent but the loader returned a
//                                non-empty wrapper (TTL drift / pre-etag).
//   reason="etag_redis_error" — the `get_etag` call itself failed.
pub const FLAG_DEFINITIONS_INMEM_CACHE_NO_VERSION_COUNTER: &str =
    "flags_definitions_inmem_cache_no_version_total";
// Cohort source for flag evaluation
// Labels: source="preloaded" (from flags hypercache) | source="cache_manager" (CohortCacheManager fallback)
pub const FLAG_COHORT_SOURCE_COUNTER: &str = "flags_cohort_source_total";
pub const PROPERTY_CACHE_HITS_COUNTER: &str = "flags_property_cache_hits_total";
pub const PROPERTY_CACHE_MISSES_COUNTER: &str = "flags_property_cache_misses_total";
pub const DB_PERSON_AND_GROUP_PROPERTIES_READS_COUNTER: &str =
    "flags_db_person_and_group_properties_reads_total";
pub const FLAG_REQUESTS_COUNTER: &str = "flags_requests_total";
pub const FLAG_REQUESTS_LATENCY: &str = "flags_requests_duration_ms";
pub const FLAG_QUEUE_TIME_MS: &str = "flags_queue_time_ms";
pub const FLAG_REQUEST_FAULTS_COUNTER: &str = "flags_request_faults_total";

// Pre-handler timing decomposition for `flags_queue_time_ms`.
// Together these subdivide the "Envoy stamp → handler entry" wall time into
// known synchronous pre-handler work + (residual) proxy/tower wait, so we
// can attribute spikes to the right tier instead of guessing.

// Total time spent in synchronous pre-handler work inside `endpoint::flags`
// (UA parse, IP rate-limit, token extract, token rate-limit). Labeled by
// `team_id` so noisy customers are attributable.
pub const FLAG_PRE_HANDLER_TIME_MS: &str = "flags_pre_handler_time_ms";

// Per-step rate-limit check timing. Labeled by `kind="ip"|"token"` to
// distinguish the two rate-limiter calls inside the endpoint.
pub const FLAG_RATE_LIMIT_CHECK_TIME_MS: &str = "flags_rate_limit_check_ms";

// Time spent inside `decoding::extract_token` (sync JSON DOM scan over the
// raw body). Pathological large bodies are the suspected outlier driver.
pub const FLAG_TOKEN_EXTRACT_TIME_MS: &str = "flags_token_extract_ms";

// Permit-acquisition wait time on the tower `ConcurrencyLimitLayer`.
// Populated by Phase F; emitted only when populated. No `team_id` label
// because permit wait is a property of pod-level load, not of any one team.
pub const FLAG_CONCURRENCY_LIMIT_WAIT_TIME_MS: &str = "flags_concurrency_limit_wait_ms";

// Performance monitoring
pub const DB_CONNECTION_POOL_ACTIVE_COUNTER: &str = "flags_db_connection_pool_active_total";
pub const DB_CONNECTION_POOL_IDLE_COUNTER: &str = "flags_db_connection_pool_idle_total";
pub const DB_CONNECTION_POOL_MAX_COUNTER: &str = "flags_db_connection_pool_max_total";
pub const DB_CONNECTION_POOL_SIZE_GAUGE: &str = "flags_db_connection_pool_size";

// Synchronous-path billing increment timing.
// Labeled by `outcome` ("ok" | "timeout" | "error") to isolate the happy
// path from Redis timeouts.
pub const FLAG_BILLING_INCREMENT_TIME: &str = "flags_billing_increment_time_ms";

// Counter for Redis errors observed during the synchronous billing
// increment. Labeled by `error_type` ("timeout" | "transport" | "not_found"
// | "parse" | "config") — same classification the billing flusher uses, so
// breakdowns line up across both paths. The raw error message is never used
// as a label (cardinality risk).
pub const FLAG_REQUEST_REDIS_ERROR: &str = "flag_request_redis_error";

// Billing aggregator metrics
// See `src/billing/aggregator.rs`. The accounting identity
//   flags_billing_records_total ≈ flags_billing_entries_flushed_total
//                                + flags_billing_unflushed_requests_total{cause="cap_drop"}
//                                + flags_billing_unflushed_requests_total{cause="flush_dropped_on_error"}
//                                + flags_billing_unflushed_requests_total{cause="shutdown_drop"}
//                                + flags_billing_pending_records (the residual still in `pending`)
// should hold per pod over any window. The `redis_error` cause is omitted
// from this identity because it only fires under `BailOnError` (normal
// ticks): the affected entries are requeued and eventually flush or land
// in `shutdown_drop`, so they aren't lost at the moment the error fires.
// Under `BestEffort` (shutdown) the same chunk failures are recorded only
// as `flush_dropped_on_error`, so summing `redis_error` with the other
// causes for a total-loss figure does not double-count.

// Counter, labeled by `request_type` ("decide" | "flag_definitions").
pub const FLAGS_BILLING_RECORDS: &str = "flags_billing_records_total";

// Counter: sum of `count` args across all successfully written HINCRBYs.
pub const FLAGS_BILLING_ENTRIES_FLUSHED: &str = "flags_billing_entries_flushed_total";

// Gauge of the live `pending` map size. Sustained growth is the leading
// indicator of a wedged flusher; alert when the gauge approaches
// `max_pending_entries`. Pair with `flags_billing_seconds_since_successful_flush`
// to distinguish a hung `execute_pipeline` (gauge growing, staleness rising)
// from steady-state high traffic (gauge oscillating, staleness near zero).
pub const FLAGS_BILLING_PENDING_ENTRIES: &str = "flags_billing_pending_entries";

// Gauge: sum of counts in `pending` — the per-pod count of records that
// would be lost if the process crashed at scrape time (SIGKILL past
// `terminationGracePeriodSeconds`, OOM-kill, node loss, panic). The
// crashed pod cannot emit at the moment of loss, so this gauge is the
// pre-crash signal: scrape it just before the pod is gone, and you have
// an upper bound on the loss. Use `sum(flags_billing_pending_records)`
// for fleet-wide loss exposure, and correlate per-pod spikes with
// `kube_pod_container_status_restarts_total` to attribute crash-loss to
// specific restarts. Differs from `flags_billing_pending_entries`
// (number of distinct keys), which can stay flat while record counts
// per key climb.
pub const FLAGS_BILLING_PENDING_RECORDS: &str = "flags_billing_pending_records";

// Gauge: seconds elapsed since the last successful flush (0 until the
// first successful flush completes).
pub const FLAGS_BILLING_SECONDS_SINCE_SUCCESSFUL_FLUSH: &str =
    "flags_billing_seconds_since_successful_flush";

pub const FLAGS_BILLING_FLUSH_DURATION_MS: &str = "flags_billing_flush_duration_ms";

// Histogram of per-call `record()` latency in microseconds, with no labels
// to keep the hot-path emission allocation-free. The expected uncontended
// p50 is sub-microsecond (one atomic increment + a hash + a HashMap entry
// op). p99 climbing while p50 stays flat is the canonical signature of
// `pending` mutex contention — this metric is the sole signal for it, since
// `record()` would otherwise be invisible to monitoring.
pub const FLAGS_BILLING_RECORD_DURATION_US: &str = "flags_billing_record_duration_us";

// Counter: flusher-side Redis failures, labeled by `error_type`
// ("timeout" | "transport" | "not_found" | "parse" | "config"). Alert on
// `rate(flags_billing_flush_errors_total[1m]) > 0 for: 30s` to catch a
// wedged Redis link without a separate consecutive-failures gauge.
pub const FLAGS_BILLING_FLUSH_ERRORS: &str = "flags_billing_flush_errors_total";

// Counter: billable requests that did not reach Redis, labeled by `cause`.
// `sum(rate(flags_billing_unflushed_requests_total[5m]))` is the
// one-expression billing-leak rate. Cause values:
//   - "cap_drop": dropped at the hot path because `pending_entries` was at
//     `max_pending_entries` and the incoming key was new. Tripwire — any
//     non-zero rate is an incident signal.
//   - "flush_dropped_on_error": drained from `pending`, then lost because a
//     flush chunk errored AND the flush policy couldn't retry. In practice
//     only fires on the shutdown path (`BestEffort`); normal ticks
//     (`BailOnError`) re-queue failed entries back into `pending`.
//   - "shutdown_drop": entries lost during shutdown because the final flush
//     timed out or panicked. SIGKILL past the grace window lands here.
//   - "redis_error": affected-request count for chunks that hit a Redis
//     error during a normal-tick flush. Only emitted under `BailOnError`:
//     includes the failing chunk plus the unattempted remainder so the
//     rate reflects all requests blocked by the error, not just the chunk
//     that hit it. These records are requeued and retried, so this label
//     is an "incident magnitude" signal rather than a terminal-loss
//     signal. Suppressed under `BestEffort` (shutdown) where the same
//     counts terminally land in `flush_dropped_on_error` — emitting both
//     would double-count when summing causes for a total-loss figure.
pub const FLAGS_BILLING_UNFLUSHED_REQUESTS: &str = "flags_billing_unflushed_requests_total";

// Flag evaluation timing
pub const FLAG_EVALUATION_TIME: &str = "flags_evaluation_time";
pub const FLAG_HASH_KEY_PROCESSING_TIME: &str = "flags_hash_key_processing_time";
pub const FLAG_DB_PROPERTIES_FETCH_TIME: &str = "flags_properties_db_fetch_time";
pub const FLAG_GROUP_DB_FETCH_TIME: &str = "flags_groups_db_fetch_time"; // this is how long it takes to fetch the group type mappings from the DB
pub const FLAG_GROUP_CACHE_FETCH_TIME: &str = "flags_groups_cache_fetch_time"; // this is how long it takes to fetch the group type mappings from the cache
pub const FLAG_GET_MATCH_TIME: &str = "flags_get_match_time";
pub const FLAG_EVALUATE_ALL_CONDITIONS_TIME: &str = "flags_evaluate_all_conditions_time";
pub const FLAG_PERSON_QUERY_TIME: &str = "flags_person_query_time";
pub const FLAG_DEFINITION_QUERY_TIME: &str = "flags_definition_query_time";
pub const FLAG_PERSON_PROCESSING_TIME: &str = "flags_person_processing_time";
pub const FLAG_COHORT_QUERY_TIME: &str = "flags_cohort_query_time";
pub const FLAG_COHORT_PROCESSING_TIME: &str = "flags_cohort_processing_time";
pub const FLAG_REALTIME_COHORT_QUERY_TIME: &str = "flags_realtime_cohort_query_time";
pub const FLAG_REALTIME_COHORT_QUERY_ERROR_COUNTER: &str =
    "flags_realtime_cohort_query_error_total";
pub const FLAG_GROUP_QUERY_TIME: &str = "flags_group_query_time";
pub const FLAG_GROUP_PROCESSING_TIME: &str = "flags_group_processing_time";
pub const FLAG_DB_CONNECTION_TIME: &str = "flags_db_connection_time";

// Flag request kludges (to see how often we have to massage our request data to be able to parse it)
pub const FLAG_REQUEST_KLUDGE_COUNTER: &str = "flags_request_kludge_total";

// New diagnostic metrics for pool exhaustion investigation
pub const FLAG_POOL_UTILIZATION_GAUGE: &str = "flags_pool_utilization_ratio";
pub const FLAG_CONNECTION_HOLD_TIME: &str = "flags_connection_hold_time_ms";
pub const FLAG_EXPERIENCE_CONTINUITY_REQUESTS_COUNTER: &str =
    "flags_experience_continuity_requests_total";

// Experience continuity optimization metric
// Tracks requests where optimization could apply, with status label:
// - status="skipped": lookup was actually skipped (optimization enabled, no flags needed it)
// - status="eligible": lookup could be skipped but wasn't (optimization feature is disabled)
pub const FLAG_EXPERIENCE_CONTINUITY_OPTIMIZED: &str =
    "flags_experience_continuity_optimized_total";

// Hash key override query result metric
// Tracks the result of hash key override queries to understand cache optimization potential
// Labels: result="empty" (no overrides found) | result="has_overrides" (overrides exist)
pub const FLAG_HASH_KEY_QUERY_RESULT: &str = "flags_hash_key_query_result_total";

// Flag definitions rate limiting
pub const FLAG_DEFINITIONS_RATE_LIMITED_COUNTER: &str = "flags_flag_definitions_rate_limited_total";
pub const FLAG_DEFINITIONS_RATE_LIMIT_BYPASSED_COUNTER: &str =
    "flags_flag_definitions_rate_limit_bypassed_total";
pub const FLAG_DEFINITIONS_REQUESTS_COUNTER: &str = "flags_flag_definitions_requests_total";

// Flag definitions cache metrics
// Labels: source (redis, s3, fallback)
pub const FLAG_DEFINITIONS_CACHE_HIT_COUNTER: &str = "flags_flag_definitions_cache_hit_total";
// Labels: reason (cache_miss, s3_error, redis_error, json_parse_error, timeout)
pub const FLAG_DEFINITIONS_CACHE_MISS_COUNTER: &str = "flags_flag_definitions_cache_miss_total";

// Flag definitions ETag metrics
// Labels: result (hit = 304, miss = 200 with stale etag, none = 200 without etag, redis_error = etag read failed)
pub const FLAG_DEFINITIONS_ETAG_COUNTER: &str = "flags_flag_definitions_etag_total";

// Flag definitions auth method
// Labels: method (secret_api_key, personal_api_key) — Rust only supports these two; Python also tracks oauth, jwt, session, other
pub const FLAG_DEFINITIONS_AUTH_COUNTER: &str = "flags_flag_definitions_auth_total";

// Request-level timeout (tower TimeoutLayer killed the request before completion)
pub const FLAG_REQUEST_TIMEOUT_COUNTER: &str = "flags_request_timeout_total";

// Timeout tracking and classification
pub const FLAG_ACQUIRE_TIMEOUT_COUNTER: &str = "flags_acquire_timeout_total";

// Error classification
pub const FLAG_DATABASE_ERROR_COUNTER: &str = "flags_database_error_total";

// Dependency graph build metrics
pub const FLAG_DEPENDENCY_GRAPH_BUILD_COUNTER: &str = "flags_dependency_graph_build_total";
pub const FLAG_DEPENDENCY_GRAPH_BUILD_TIME: &str = "flags_dependency_graph_build_ms";
pub const FLAG_MISSING_REQUESTED_FLAG_KEY: &str = "missing_requested_flag_key";

// Tombstone metric for tracking "impossible" failures that should never happen in production
// Different failure types are tracked via the "failure_type" label
pub const TOMBSTONE_COUNTER: &str = "posthog_tombstone_total";

// DB operations per request metric
// Tracks the count of DB operations per request, labeled by team_id and operation_type.
// This surfaces teams generating excessive DB load regardless of individual query latency.
// Labels: team_id, operation_type (person_query, cohort_query, group_query)
pub const FLAG_DB_OPERATIONS_PER_REQUEST: &str = "flags_db_operations_per_request";

// Rayon dispatcher metrics
// These track semaphore backpressure on the parallel evaluation path.

// Time spent waiting for a semaphore permit before entering the Rayon pool (histogram, ms).
// Near-zero means the pool is not saturated; high values mean batches are queueing.
pub const RAYON_DISPATCHER_SEMAPHORE_WAIT_TIME: &str = "flags_rayon_dispatcher_semaphore_wait_ms";

// Number of semaphore permits available at dispatch time (gauge).
// Consistently 0 means the Rayon pool is fully saturated.
pub const RAYON_DISPATCHER_AVAILABLE_PERMITS: &str = "flags_rayon_dispatcher_available_permits";

// Time spent executing work on the Rayon pool, excluding semaphore wait (histogram, ms).
// Compare with RAYON_DISPATCHER_SEMAPHORE_WAIT_TIME to understand whether tail latency
// comes from semaphore contention or actual computation time.
pub const RAYON_DISPATCHER_EXECUTION_TIME: &str = "flags_rayon_dispatcher_execution_ms";

// Counter of semaphore acquisitions that had to wait (no permits available).
// The ratio contended/total indicates how often the Rayon pool is at capacity.
pub const RAYON_DISPATCHER_CONTENDED_ACQUIRES: &str =
    "flags_rayon_dispatcher_contended_acquires_total";

// Total semaphore acquisitions (counter). Used as denominator for contention ratio.
pub const RAYON_DISPATCHER_TOTAL_ACQUIRES: &str = "flags_rayon_dispatcher_acquires_total";

// Number of batch tasks currently executing on the Rayon pool (gauge).
// With N semaphore permits, this should stay in [0, N]. Consistently at N
// means the pool is saturated and the semaphore is the bottleneck.
pub const RAYON_DISPATCHER_INFLIGHT_TASKS: &str = "flags_rayon_dispatcher_inflight_tasks";

// Counter of semaphore acquisitions that timed out (request failed fast with 504).
// Non-zero means the configured timeout is being hit and requests are being
// redistributed to other pods via ingress retry.
pub const RAYON_DISPATCHER_SEMAPHORE_TIMEOUTS: &str =
    "flags_rayon_dispatcher_semaphore_timeouts_total";

// Flag batch evaluation metrics
// These track the performance difference between sequential and parallel evaluation strategies.
// Used for A/B testing and tuning the PARALLEL_EVAL_THRESHOLD.

// Time spent evaluating a batch of flags (histogram)
// Labels: evaluation_type ("sequential" or "parallel")
pub const FLAG_BATCH_EVALUATION_TIME: &str = "flags_batch_evaluation_time_ms";

// Counter for evaluation batches by type
// Labels: evaluation_type ("sequential" or "parallel")
pub const FLAG_BATCH_EVALUATION_COUNTER: &str = "flags_batch_evaluation_total";

// Histogram of flag counts per batch evaluation
// Labels: evaluation_type ("sequential" or "parallel")
pub const FLAG_BATCH_SIZE: &str = "flags_batch_size";

// Tokio runtime metrics
// These track worker thread utilization to inform thread pool sizing decisions.
// Sampled periodically by TokioRuntimeMonitor (default: every 15s).

// Fraction of wall-clock time that workers spent executing tasks (gauge, 0.0–1.0).
// Computed as: sum(worker_busy_duration_delta) / (elapsed * num_workers).
// < 0.3 means workers are idle 70%+ of the time — room to reduce worker count.
// > 0.8 means approaching saturation.
pub const TOKIO_RUNTIME_BUSY_RATIO: &str = "flags_tokio_busy_ratio";

// Number of tasks currently alive (spawned but not yet completed) on the runtime (gauge).
pub const TOKIO_RUNTIME_ALIVE_TASKS: &str = "flags_tokio_alive_tasks";

// Tasks pending in the runtime's global injection queue (gauge).
// Sustained values > 0 indicate workers cannot drain tasks fast enough.
pub const TOKIO_RUNTIME_GLOBAL_QUEUE_DEPTH: &str = "flags_tokio_global_queue_depth";

// Number of configured Tokio worker threads (gauge, constant after startup).
pub const TOKIO_RUNTIME_NUM_WORKERS: &str = "flags_tokio_num_workers";

// Per-worker local queue depth (gauge). Labels: worker="0", worker="1", etc.
// High values indicate a specific worker is overloaded.
pub const TOKIO_WORKER_LOCAL_QUEUE_DEPTH: &str = "flags_tokio_worker_local_queue_depth";

// Per-worker poll count delta over the sampling interval (gauge). Labels: worker.
// Shows throughput per worker — large imbalances suggest uneven task distribution.
pub const TOKIO_WORKER_POLL_DELTA: &str = "flags_tokio_worker_poll_delta";

// Per-worker park count delta over the sampling interval (gauge). Labels: worker.
// A park event means the worker went idle. High park rates indicate light workloads.
pub const TOKIO_WORKER_PARK_DELTA: &str = "flags_tokio_worker_park_delta";

// Per-worker busy duration over the sampling interval in seconds (gauge). Labels: worker.
// Used to detect load imbalance across workers.
pub const TOKIO_WORKER_BUSY_DURATION_DELTA: &str = "flags_tokio_worker_busy_duration_delta_secs";

// Number of threads in the blocking thread pool (gauge).
pub const TOKIO_BLOCKING_THREADS: &str = "flags_tokio_blocking_threads";

// Idle threads in the blocking thread pool (gauge).
pub const TOKIO_IDLE_BLOCKING_THREADS: &str = "flags_tokio_idle_blocking_threads";

// Tasks waiting for a blocking thread (gauge).
// High values indicate spawn_blocking contention.
pub const TOKIO_BLOCKING_QUEUE_DEPTH: &str = "flags_tokio_blocking_queue_depth";

// Mean poll duration per worker in microseconds (gauge). Labels: worker.
// Long poll times can indicate blocking or CPU-heavy futures on the Tokio runtime.
pub const TOKIO_WORKER_MEAN_POLL_TIME_US: &str = "flags_tokio_worker_mean_poll_time_us";

// Times a worker's local queue overflowed to the global queue (gauge, delta). Labels: worker.
// Non-zero indicates a worker couldn't keep up and had to shed work.
pub const TOKIO_WORKER_OVERFLOW_DELTA: &str = "flags_tokio_worker_overflow_delta";

// Number of tasks stolen from other workers (gauge, delta). Labels: worker.
// Active stealing indicates work imbalance being corrected by the scheduler.
pub const TOKIO_WORKER_STEAL_DELTA: &str = "flags_tokio_worker_steal_delta";
