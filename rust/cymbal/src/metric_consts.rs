pub const ERRORS: &str = "cymbal_errors";
pub const SOURCEMAP_HEADER_FOUND: &str = "cymbal_sourcemap_header_found";
pub const SOURCEMAP_BODY_REF_FOUND: &str = "cymbal_sourcemap_body_ref_found";
pub const SOURCEMAP_NOT_FOUND: &str = "cymbal_sourcemap_not_found";
pub const SOURCEMAP_BODY_FETCHES: &str = "cymbal_sourcemap_body_fetches";
pub const STORE_CACHE_HITS: &str = "cymbal_store_cache_hits";
pub const STORE_CACHE_MISSES: &str = "cymbal_store_cache_misses";
pub const STORE_CACHED_BYTES: &str = "cymbal_store_cached_bytes";
pub const STORE_CACHE_EVICTIONS: &str = "cymbal_store_cache_evictions";
pub const STORE_CACHE_EVICTION_RUNS: &str = "cymbal_store_cache_eviction_runs";
pub const PER_FRAME_TIME: &str = "cymbal_per_frame_time";
pub const SYMBOL_SET_DB_FETCHES: &str = "cymbal_symbol_set_db_fetches";
pub const SYMBOL_SET_DB_HITS: &str = "cymbal_symbol_set_db_hits";
pub const SYMBOL_SET_DB_MISSES: &str = "cymbal_symbol_set_db_misses";
pub const SYMBOL_SET_SAVED: &str = "cymbal_symbol_set_saved";
pub const SAVED_SYMBOL_SET_LOADED: &str = "cymbal_saved_symbol_set_loaded";
pub const SAVED_SYMBOL_SET_ERROR_RETURNED: &str = "cymbal_saved_symbol_set_error_returned";
pub const SYMBOL_SET_FETCH_RETRY: &str = "cymbal_symbol_set_fetch_retry";
pub const FRAME_RESOLVED: &str = "cymbal_frame_resolved";
pub const FRAME_CACHE_HITS: &str = "cymbal_frame_cache_hits";
pub const FRAME_CACHE_MISSES: &str = "cymbal_frame_cache_misses";
pub const FRAME_DB_HITS: &str = "cymbal_frame_db_hits";
pub const FRAME_DB_MISSES: &str = "cymbal_frame_db_misses";
pub const FRAME_NOT_RESOLVED: &str = "cymbal_frame_not_resolved";
pub const S3_FETCH: &str = "cymbal_s3_fetch";
// S3 GET body size, in bytes, taken from the `Content-Length` header on the GET response
// (so it's recorded before we collect the body — sets us up to enforce a size cap here later).
pub const S3_FETCHED_BYTES: &str = "cymbal_s3_fetched_bytes";
pub const S3_PUT: &str = "cymbal_s3_put";
// S3 PUT body size, in bytes, observed at the call site.
pub const S3_PUT_BYTES: &str = "cymbal_s3_put_bytes";
pub const SOURCEMAP_FETCH: &str = "cymbal_sourcemap_fetch";
// Size of an external (non-S3) sourcemap or minified source fetch, in bytes after decoding
// the HTTP response body. Labelled by `kind` (`source` / `sourcemap`).
pub const SOURCEMAP_EXTERNAL_BYTES: &str = "cymbal_sourcemap_external_bytes";
pub const SAVE_SYMBOL_SET: &str = "cymbal_save_symbol_set";
pub const SOURCEMAP_PARSE: &str = "cymbal_sourcemap_parse";
// Decompressed size of a parsed symbol set, in bytes. Labelled by `kind`
// (`sourcemap` / `hermes` / `proguard` / `apple`).
pub const SYMBOL_SET_DECOMPRESSED_BYTES: &str = "cymbal_symbol_set_decompressed_bytes";

// Histogram buckets for the byte-shaped metrics above. The default
// `common_metrics` buckets are tuned for milliseconds of latency and saturate
// at 10_000 — every multi-KB fetch would land in the `+Inf` bucket. These
// cover 1 KiB → 1 GiB with extra granularity in the multi-MB range where any
// reasonable size cap would live.
pub const BYTE_HISTOGRAM_BUCKETS: &[f64] = &[
    1_024.0,         // 1 KiB
    10_240.0,        // 10 KiB
    102_400.0,       // 100 KiB
    524_288.0,       // 512 KiB
    1_048_576.0,     // 1 MiB
    5_242_880.0,     // 5 MiB
    10_485_760.0,    // 10 MiB
    26_214_400.0,    // 25 MiB
    52_428_800.0,    // 50 MiB
    104_857_600.0,   // 100 MiB
    268_435_456.0,   // 256 MiB
    536_870_912.0,   // 512 MiB
    1_073_741_824.0, // 1 GiB
];
pub const ISSUE_CREATED: &str = "cymbal_issue_created";
pub const ISSUE_REOPENED: &str = "cymbal_issue_reopened";
pub const FRAME_RESOLUTION_RESULTS_DELETED: &str = "cymbal_frame_resolution_results_deleted";
pub const CHUNK_ID_NOT_FOUND: &str = "cymbal_chunk_id_not_found";
pub const CHUNK_ID_FAILURE_FETCHED: &str = "cymbal_chunk_id_failure_fetched";
pub const CHUNK_ID_RESCUED_FROM_BODY: &str = "cymbal_chunk_id_rescued_from_body";
pub const SUPPRESSED_ISSUE_DROPPED_EVENTS: &str = "cymbal_suppressed_issue_drop";
pub const ASSIGNMENT_RULES_PROCESSING_TIME: &str = "cymbal_assignment_rules_processing_time";
pub const ANCILLARY_CACHE: &str = "cymbal_ancillary_cache";
pub const ASSIGNMENT_RULES_FOUND: &str = "cymbal_assignment_rules_found";
pub const ASSIGNMENT_RULES_TRIED: &str = "cymbal_assignment_rules_tried";
pub const AUTO_ASSIGNMENTS: &str = "cymbal_auto_assignments";
pub const ASSIGNMENT_RULES_DISABLED: &str = "cymbal_assignment_rules_disabled";
pub const GROUPING_RULES_DISABLED: &str = "cymbal_grouping_rules_disabled";
pub const GROUPING_RULES_PROCESSING_TIME: &str = "cymbal_grouping_rules_processing_time";
pub const GROUPING_RULES_FOUND: &str = "cymbal_grouping_rules_found";
pub const GROUPING_RULES_TRIED: &str = "cymbal_grouping_rules_tried";
pub const CUSTOM_GROUPED_EVENTS: &str = "cymbal_custom_grouped_events";
pub const POSTHOG_SDK_EXCEPTION_RESOLVED: &str = "cymbal_posthog_sdk_exception_resolved";
pub const SUSPICIOUS_FRAMES_DETECTED: &str = "cymbal_suspicious_frames_detected";
pub const LEGACY_JS_FRAME_RESOLVED: &str = "cymbal_legacy_js_frame_resolved";
pub const JAVA_EXCEPTION_REMAP_FAILED: &str = "cymbal_java_exception_remap_failed";

// HTTP /process observability metrics
pub const PROCESS_REQUESTS_TOTAL: &str = "cymbal_process_requests_total";
pub const PROCESS_REQUEST_DURATION_SECONDS: &str = "cymbal_process_request_duration_seconds";
pub const PROCESS_BATCH_EVENTS: &str = "cymbal_process_batch_events";
// Gauge of events currently admitted by the HTTP processing backpressure limiter.
pub const PROCESS_IN_FLIGHT: &str = "cymbal_process_in_flight";

// Disposition-based /v2/resolve observability. These count individual event
// outcomes (labelled by `{action, reason}`) and surface the new contract's
// per-event classification to operators. Combined with PROCESS_REQUESTS_TOTAL
// (which counts whole requests), they give a complete picture of cymbal's
// behaviour under load.
pub const DISPOSITIONS_EMITTED_TOTAL: &str = "cymbal_event_dispositions_emitted_total";
// Wall-clock time spent producing the disposition for a single event, including
// any sub-stage work. Tells us where the per-event deadline budget is going.
pub const DISPOSITION_DURATION_SECONDS: &str = "cymbal_event_disposition_duration_seconds";
// Increments whenever an event disposition had to be filled in as a fallback
// because the per-event deadline elapsed mid-processing. Distinct from
// "event_dispositions_emitted_total{action=retry,reason=deadline_exceeded}" because it
// signals the deadline triggered the fallback, rather than a stage choosing
// to emit a retry disposition on its own.
pub const DISPOSITION_DEADLINE_FALLBACK_TOTAL: &str =
    "cymbal_event_disposition_deadline_fallback_total";
// Increments whenever per-event processing panicked. A non-zero rate means
// cymbal has bugs being absorbed silently as `retry` dispositions; the panic
// counter is the trail for finding them.
pub const DISPOSITION_PANIC_TOTAL: &str = "cymbal_event_disposition_panic_total";
// Increments when the whole-request deadline elapsed with events still
// in flight. Should be rare in steady state — per-event deadlines should
// bring each event home before the request deadline.
pub const DISPOSITION_REQUEST_DEADLINE_EXHAUSTED_TOTAL: &str =
    "cymbal_event_disposition_request_deadline_exhausted_total";

// Spike detection metrics
pub const SPIKE_INCREMENT_ISSUE_BUCKETS_TIME: &str = "cymbal_spike_increment_issue_buckets_time";
pub const SPIKE_INCREMENT_TEAM_BUCKETS_TIME: &str = "cymbal_spike_increment_team_buckets_time";
pub const SPIKE_GET_SPIKING_ISSUES_TIME: &str = "cymbal_spike_get_spiking_issues_time";
pub const SPIKE_ACQUIRE_LOCKS_TIME: &str = "cymbal_spike_acquire_locks_time";
pub const SPIKE_EMIT_EVENTS_TIME: &str = "cymbal_spike_emit_events_time";
pub const SPIKE_ISSUES_CHECKED: &str = "cymbal_spike_issues_checked";
pub const SPIKE_ISSUES_SPIKING: &str = "cymbal_spike_issues_spiking";
pub const SPIKE_ISSUES_BLOCKED_BY_COOLDOWN: &str = "cymbal_spike_issues_blocked_by_cooldown";

// Signal metrics
pub const SIGNAL_EMITTED: &str = "cymbal_signal_emitted";
pub const SIGNAL_EMIT_FAILED: &str = "cymbal_signal_emit_failed";
pub const SIGNAL_EMIT_RESPONSE: &str = "cymbal_signal_emit_response";

// Stages Name.
// We want to keep previous value for comparison, can be changed later on
pub const HTTP_EXCEPTION_PIPELINE: &str = "cymbal_http_exception_pipeline";
pub const EXCEPTION_PROCESSING_PIPELINE: &str = "cymbal_exception_processing_time";
pub const PRE_PROCESSING_STAGE: &str = "cymbal_exception_pre_processing_stage";
pub const POST_PROCESSING_STAGE: &str = "cymbal_exception_post_processing_stage";
pub const RESOLUTION_STAGE: &str = "cymbal_stack_processing_time";
pub const LINKING_STAGE: &str = "cymbal_issue_processing_time";
pub const GROUPING_STAGE: &str = "cymbal_exception_grouping_stage";
pub const ALERTING_STAGE: &str = "cymbal_exception_alerting_stage";
pub const SPIKE_ALERT_STAGE: &str = "cymbal_spike_detection_time";

// Operators
pub const FRAME_RESOLVER_OPERATOR: &str = "cymbal_frame_batch_time";
pub const EXCEPTION_RESOLVER_OPERATOR: &str = "cymbal_exception_exception_resolver_operator";
pub const PROPERTIES_RESOLVER_OPERATOR: &str = "cymbal_exception_properties_resolver_operator";
pub const ISSUE_LINKER_OPERATOR: &str = "cymbal_exception_issue_linker_operator";
pub const ISSUE_SUPPRESSION_OPERATOR: &str = "cymbal_exception_issue_suppression_operator";
pub const RULE_SUPPRESSION_OPERATOR: &str = "cymbal_exception_rule_suppression_operator";
pub const FINGERPRINT_GENERATOR_OPERATOR: &str = "cymbal_exception_fingerprint_generator_operator";
pub const RULE_SUPPRESSED_EVENTS: &str = "cymbal_rule_suppressed_events";
pub const SUPPRESSION_RULES_TRIED: &str = "cymbal_suppression_rules_tried";
pub const SUPPRESSION_RULES_DISABLED: &str = "cymbal_suppression_rules_disabled";
