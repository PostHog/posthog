pub const FLAG_EVALUATION_ERROR_COUNTER: &str = "flag_evaluation_error_total";
pub const FLAG_CACHE_HIT_COUNTER: &str = "flag_cache_hit_total";
pub const FLAG_HASH_KEY_WRITES_COUNTER: &str = "flag_hash_key_writes_total";
// TODO add metrics for failing to update redis?  Does that really happen?
// maybe worth adding for rollout, since writing to redis is a critical path thing
