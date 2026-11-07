use logs_ingestion::js::JsObject;
use logs_ingestion::service::node_env::{get_number, get_string};

/// The `METRICS_LIMITER_*` keys of `MetricsIngestionConsumerConfig`.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct MetricsLimiterConfig {
    pub enabled_teams: String,
    pub disabled_for_teams: String,
    pub bucket_size_kb: f64,
    pub refill_rate_kb_per_second: f64,
    pub ttl_seconds: f64,
    pub team_bucket_size_kb: String,
    pub team_refill_rate_kb_per_second: String,
}

impl MetricsLimiterConfig {
    pub fn from_node_config(c: &JsObject) -> Self {
        Self {
            enabled_teams: get_string(c, "METRICS_LIMITER_ENABLED_TEAMS"),
            disabled_for_teams: get_string(c, "METRICS_LIMITER_DISABLED_FOR_TEAMS"),
            bucket_size_kb: get_number(c, "METRICS_LIMITER_BUCKET_SIZE_KB"),
            refill_rate_kb_per_second: get_number(c, "METRICS_LIMITER_REFILL_RATE_KB_PER_SECOND"),
            ttl_seconds: get_number(c, "METRICS_LIMITER_TTL_SECONDS"),
            team_bucket_size_kb: get_string(c, "METRICS_LIMITER_TEAM_BUCKET_SIZE_KB"),
            team_refill_rate_kb_per_second: get_string(
                c,
                "METRICS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND",
            ),
        }
    }
}
