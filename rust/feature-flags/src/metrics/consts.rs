pub const FLAG_EVALUATION_ERROR_COUNTER: &str = "flags_flag_evaluation_error_total";
pub const FLAG_CACHE_HIT_COUNTER: &str = "flags_flag_cache_hit_total";
pub const FLAG_CACHE_ERRORS_COUNTER: &str = "flags_flag_cache_errors_total";
pub const FLAG_HASH_KEY_WRITES_COUNTER: &str = "flags_flag_hash_key_writes_total";
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

// Timing metrics
pub const FLAG_EVALUATION_TIME: &str = "flags_evaluation_time";
pub const FLAG_HASH_KEY_PROCESSING_TIME: &str = "flags_hash_key_processing_time";
pub const FLAG_LOCAL_PROPERTY_OVERRIDE_MATCH_TIME: &str =
    "flags_local_property_override_match_time";
pub const FLAG_DB_PROPERTIES_FETCH_TIME: &str = "flags_properties_db_fetch_time";
pub const FLAG_GROUP_FETCH_TIME: &str = "flags_groups_cache_fetch_time";
pub const FLAG_GET_MATCH_TIME: &str = "flags_get_match_time";
pub const FLAG_EVALUATE_ALL_CONDITIONS_TIME: &str = "flags_evaluate_all_conditions_time";
pub const FLAG_PERSON_QUERY_TIME: &str = "flags_person_query_time";
pub const FLAG_PERSON_PROCESSING_TIME: &str = "flags_person_processing_time";
pub const FLAG_COHORT_QUERY_TIME: &str = "flags_cohort_query_time";
pub const FLAG_COHORT_PROCESSING_TIME: &str = "flags_cohort_processing_time";
pub const FLAG_GROUP_QUERY_TIME: &str = "flags_group_query_time";
pub const FLAG_GROUP_PROCESSING_TIME: &str = "flags_group_processing_time";
pub const FLAG_DB_CONNECTION_TIME: &str = "flags_db_connection_time";
