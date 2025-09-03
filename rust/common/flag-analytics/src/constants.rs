/// Constants for flag analytics

/// Prefix for survey targeting flags (these are not billable)
pub const SURVEY_TARGETING_FLAG_PREFIX: &str = "survey-targeting-";

/// Duration in seconds for Redis time buckets (2-minute intervals)
pub const CACHE_BUCKET_SIZE: u64 = 60 * 2;
