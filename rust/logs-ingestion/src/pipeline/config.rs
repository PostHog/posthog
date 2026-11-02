//! The consumer settings that `LogsIngestionConsumer` reads from `LogsIngestionConsumerConfig`.

use crate::js::{JsObject, JsValue};

#[derive(Debug, Clone, Default, PartialEq)]
pub struct LogsIngestionConsumerConfig {
    pub limiter_enabled_teams: String,
    pub limiter_disabled_for_teams: String,
    pub limiter_bucket_size_kb: f64,
    pub limiter_refill_rate_kb_per_second: f64,
    pub limiter_ttl_seconds: f64,
    pub limiter_team_bucket_size_kb: String,
    pub limiter_team_refill_rate_kb_per_second: String,
    pub sampling_enabled_teams: String,
    pub sampling_killswitch: bool,
    pub metrics_rules_enabled_teams: String,
    pub metrics_rules_killswitch: bool,
    pub default_metric_rules_enabled_teams: String,
    pub retention_enabled_teams: String,
    pub retention_killswitch: bool,
    pub backfill_enabled_teams: String,
    pub internal_ingestion_enabled_teams: String,
    pub internal_ingestion_signing_keys: String,
    pub pattern_masking_enabled_teams: String,
    pub json_attribute_parsing_enabled_teams: String,
    pub json_attribute_extraction_enabled_teams: String,
    pub billing_prorate_enabled: bool,
    pub transformations_enabled_teams: String,
    pub transformations_killswitch: bool,
}

fn string(config: &JsObject, key: &str) -> String {
    match config.get(key) {
        Some(JsValue::String(s)) => s.to_utf8_lossy().into_owned(),
        Some(JsValue::Number(n)) => crate::js::number_to_string(*n),
        _ => String::new(),
    }
}

fn number(config: &JsObject, key: &str) -> f64 {
    match config.get(key) {
        Some(JsValue::Number(n)) => *n,
        _ => 0.0,
    }
}

fn boolean(config: &JsObject, key: &str) -> bool {
    matches!(config.get(key), Some(JsValue::Bool(true)))
}

impl LogsIngestionConsumerConfig {
    pub fn from_logs_config(c: &JsObject) -> Self {
        Self {
            limiter_enabled_teams: string(c, "LOGS_LIMITER_ENABLED_TEAMS"),
            limiter_disabled_for_teams: string(c, "LOGS_LIMITER_DISABLED_FOR_TEAMS"),
            limiter_bucket_size_kb: number(c, "LOGS_LIMITER_BUCKET_SIZE_KB"),
            limiter_refill_rate_kb_per_second: number(c, "LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND"),
            limiter_ttl_seconds: number(c, "LOGS_LIMITER_TTL_SECONDS"),
            limiter_team_bucket_size_kb: string(c, "LOGS_LIMITER_TEAM_BUCKET_SIZE_KB"),
            limiter_team_refill_rate_kb_per_second: string(
                c,
                "LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND",
            ),
            sampling_enabled_teams: string(c, "LOGS_SAMPLING_ENABLED_TEAMS"),
            sampling_killswitch: boolean(c, "LOGS_SAMPLING_KILLSWITCH"),
            metrics_rules_enabled_teams: string(c, "LOGS_METRICS_RULES_ENABLED_TEAMS"),
            metrics_rules_killswitch: boolean(c, "LOGS_METRICS_RULES_KILLSWITCH"),
            default_metric_rules_enabled_teams: string(
                c,
                "LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS",
            ),
            retention_enabled_teams: string(c, "LOGS_RETENTION_ENABLED_TEAMS"),
            retention_killswitch: boolean(c, "LOGS_RETENTION_KILLSWITCH"),
            backfill_enabled_teams: string(c, "LOGS_BACKFILL_ENABLED_TEAMS"),
            internal_ingestion_enabled_teams: string(c, "LOGS_INTERNAL_INGESTION_ENABLED_TEAMS"),
            internal_ingestion_signing_keys: string(c, "LOGS_INTERNAL_INGESTION_SIGNING_KEYS"),
            pattern_masking_enabled_teams: string(c, "LOGS_PATTERN_MASKING_ENABLED_TEAMS"),
            json_attribute_parsing_enabled_teams: string(
                c,
                "LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS",
            ),
            json_attribute_extraction_enabled_teams: string(
                c,
                "LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS",
            ),
            billing_prorate_enabled: boolean(c, "LOGS_BILLING_PRORATE_ENABLED"),
            transformations_enabled_teams: string(c, "LOGS_TRANSFORMATIONS_ENABLED_TEAMS"),
            transformations_killswitch: boolean(c, "LOGS_TRANSFORMATIONS_KILLSWITCH"),
        }
    }

    pub fn from_traces_config(c: &JsObject) -> Self {
        Self {
            limiter_enabled_teams: string(c, "TRACES_LIMITER_ENABLED_TEAMS"),
            limiter_disabled_for_teams: string(c, "TRACES_LIMITER_DISABLED_FOR_TEAMS"),
            limiter_bucket_size_kb: number(c, "TRACES_LIMITER_BUCKET_SIZE_KB"),
            limiter_refill_rate_kb_per_second: number(
                c,
                "TRACES_LIMITER_REFILL_RATE_KB_PER_SECOND",
            ),
            limiter_ttl_seconds: number(c, "TRACES_LIMITER_TTL_SECONDS"),
            limiter_team_bucket_size_kb: string(c, "TRACES_LIMITER_TEAM_BUCKET_SIZE_KB"),
            limiter_team_refill_rate_kb_per_second: string(
                c,
                "TRACES_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND",
            ),
            metrics_rules_enabled_teams: string(c, "TRACES_METRICS_RULES_ENABLED_TEAMS"),
            metrics_rules_killswitch: boolean(c, "TRACES_METRICS_RULES_KILLSWITCH"),
            default_metric_rules_enabled_teams: string(
                c,
                "TRACES_DEFAULT_METRIC_RULES_ENABLED_TEAMS",
            ),
            retention_enabled_teams: string(c, "TRACES_RETENTION_ENABLED_TEAMS"),
            retention_killswitch: boolean(c, "TRACES_RETENTION_KILLSWITCH"),
            // Internal batches are logs only, so a signed traces batch is still billed.
            internal_ingestion_signing_keys: String::new(),
            internal_ingestion_enabled_teams: String::new(),
            ..Self::from_logs_config(c)
        }
    }
}
