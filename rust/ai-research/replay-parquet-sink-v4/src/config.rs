use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

/// The v3 sink's default group. A v4 sink in it would take v3 partitions and read none of their topic.
const V3_PARQUET_SINK_GROUP_ID: &str = "session-replay-ml-parquet-sink";

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(from = "AI_RESEARCH_V4_INDEX_TOPIC", default = "ai_research_v4_index")]
    pub topic: String,

    #[envconfig(
        from = "AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID",
        default = "ai-research-v4-parquet-sink"
    )]
    pub group_id: String,

    #[envconfig(from = "AI_RESEARCH_V4_RRWEB_BUCKET", default = "")]
    pub rrweb_bucket: String,

    #[envconfig(from = "AI_RESEARCH_V4_PARQUET_FLUSH_INTERVAL_MS", default = "600000")]
    pub flush_interval_ms: u64,

    #[envconfig(from = "AI_RESEARCH_V4_PARQUET_MAX_ROWS", default = "1000000")]
    pub max_rows: usize,

    #[envconfig(from = "AI_RESEARCH_V4_PARQUET_MAX_BYTES", default = "134217728")]
    pub max_bytes: usize,

    #[envconfig(from = "AI_RESEARCH_V4_PARQUET_ROW_GROUP_ROWS", default = "131072")]
    pub row_group_rows: usize,

    #[envconfig(from = "METRICS_PORT", default = "9104")]
    pub metrics_port: u16,
}

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.group_id.trim().is_empty() || self.group_id == V3_PARQUET_SINK_GROUP_ID {
            return Err(
                "AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID must be set and differ from the v3 sink group".to_owned(),
            );
        }
        if self.topic.trim().is_empty() {
            return Err("AI_RESEARCH_V4_INDEX_TOPIC must be set".to_owned());
        }
        if self.rrweb_bucket.trim().is_empty() {
            return Err(
                "AI_RESEARCH_V4_RRWEB_BUCKET must be set for the v4 Parquet sink".to_owned(),
            );
        }
        if self.row_group_rows == 0 {
            return Err(
                "AI_RESEARCH_V4_PARQUET_ROW_GROUP_ROWS must be a positive integer".to_owned(),
            );
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    fn config(vars: &[(&str, &str)]) -> Config {
        let env: HashMap<String, String> = vars
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect();
        Config::init_from_hashmap(&env).unwrap()
    }

    #[test]
    fn refuses_settings_that_would_write_wrong_files() {
        let bucket = ("AI_RESEARCH_V4_RRWEB_BUCKET", "rrweb");
        assert_eq!(config(&[bucket]).validate(), Ok(()));
        assert!(config(&[]).validate().is_err());
        assert!(config(&[
            bucket,
            (
                "AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID",
                V3_PARQUET_SINK_GROUP_ID
            )
        ])
        .validate()
        .is_err());
        assert!(
            config(&[bucket, ("AI_RESEARCH_V4_PARQUET_ROW_GROUP_ROWS", "0")])
                .validate()
                .is_err()
        );
    }
}
