// Flag evaluation counters
pub const FLAG_EVALUATION_ERROR_COUNTER: &str = "flags_flag_evaluation_error_total";
pub const FLAG_CACHE_HIT_COUNTER: &str = "flags_flag_cache_hit_total";
pub const FLAG_CACHE_ERRORS_COUNTER: &str = "flags_flag_cache_errors_total";
pub const FLAG_HASH_KEY_WRITES_COUNTER: &str = "flags_flag_hash_key_writes_total";
pub const FLAG_HASH_KEY_RETRIES_COUNTER: &str = "flags_hash_key_retries_total";
pub const TEAM_CACHE_HIT_COUNTER: &str = "flags_team_cache_hit_total";
pub const TEAM_CACHE_ERRORS_COUNTER: &str = "flags_team_cache_errors_total";
pub const DB_TEAM_READS_COUNTER: &str = "flags_db_team_reads_total";
pub const TOKEN_VALIDATION_ERRORS_COUNTER: &str = "flags_token_validation_errors_total";
pub const DB_FLAG_READS_COUNTER: &str = "flags_db_flag_reads_total";
pub const DB_COHORT_READS_COUNTER: &str = "flags_db_cohort_reads_total";
pub const DB_COHORT_ERRORS_COUNTER: &str = "flags_db_cohort_errors_total";
pub const COHORT_CACHE_HIT_COUNTER: &str = "flags_cohort_cache_hit_total";
pub const COHORT_CACHE_MISS_COUNTER: &str = "flags_cohort_cache_miss_total";
pub const PROPERTY_CACHE_HITS_COUNTER: &str = "flags_property_cache_hits_total";
pub const PROPERTY_CACHE_MISSES_COUNTER: &str = "flags_property_cache_misses_total";
pub const DB_PERSON_AND_GROUP_PROPERTIES_READS_COUNTER: &str =
    "flags_db_person_and_group_properties_reads_total";
pub const FLAG_REQUESTS_COUNTER: &str = "flags_requests_total";
pub const FLAG_REQUESTS_LATENCY: &str = "flags_requests_duration_ms";
pub const FLAG_REQUEST_FAULTS_COUNTER: &str = "flags_request_faults_total";

// Performance monitoring
pub const DB_CONNECTION_POOL_ACTIVE_COUNTER: &str = "flags_db_connection_pool_active_total";
pub const DB_CONNECTION_POOL_IDLE_COUNTER: &str = "flags_db_connection_pool_idle_total";
pub const DB_CONNECTION_POOL_MAX_COUNTER: &str = "flags_db_connection_pool_max_total";

// Flag evaluation timing
pub const FLAG_EVALUATION_TIME: &str = "flags_evaluation_time";
pub const FLAG_HASH_KEY_PROCESSING_TIME: &str = "flags_hash_key_processing_time";
pub const FLAG_LOCAL_PROPERTY_OVERRIDE_MATCH_TIME: &str =
    "flags_local_property_override_match_time";
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
pub const FLAG_GROUP_QUERY_TIME: &str = "flags_group_query_time";
pub const FLAG_GROUP_PROCESSING_TIME: &str = "flags_group_processing_time";
pub const FLAG_DB_CONNECTION_TIME: &str = "flags_db_connection_time";

// Flag request kludges (to see how often we have to massage our request data to be able to parse it)
pub const FLAG_REQUEST_KLUDGE_COUNTER: &str = "flags_request_kludge_total";

// New diagnostic metrics for pool exhaustion investigation
pub const FLAG_POOL_UTILIZATION_GAUGE: &str = "flags_pool_utilization_ratio";
pub const FLAG_CONNECTION_HOLD_TIME: &str = "flags_connection_hold_time_ms";
pub const FLAG_CONNECTION_QUEUE_DEPTH_GAUGE: &str = "flags_connection_queue_depth";
pub const FLAG_READER_TIMEOUT_WITH_WRITER_STATE_COUNTER: &str =
    "flags_reader_timeout_with_writer_state_total";
pub const FLAG_EXPERIENCE_CONTINUITY_REQUESTS_COUNTER: &str =
    "flags_experience_continuity_requests_total";

// Flag definitions rate limiting
pub const FLAG_DEFINITIONS_RATE_LIMITED_COUNTER: &str = "flags_flag_definitions_rate_limited_total";
pub const FLAG_DEFINITIONS_REQUESTS_COUNTER: &str = "flags_flag_definitions_requests_total";

// Timeout tracking and classification
pub const FLAG_CLIENT_TIMEOUT_COUNTER: &str = "flags_client_timeout_total";
pub const FLAG_ACQUIRE_TIMEOUT_COUNTER: &str = "flags_acquire_timeout_total";

// Multi-connection operation tracking
pub const FLAG_MULTI_CONNECTION_OPERATION_COUNTER: &str = "flags_multi_connection_operation_total";
pub const FLAG_CONNECTION_OVERLAP_TIME_MS: &str = "flags_connection_overlap_time_ms";

// Error classification
pub const FLAG_DATABASE_ERROR_COUNTER: &str = "flags_database_error_total";
