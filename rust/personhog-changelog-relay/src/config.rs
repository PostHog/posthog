use std::time::Duration;

use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    /// The changelog's cluster; the producer settings in it tune the output producer.
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "personhog-changelog-relay")]
    pub kafka_consumer_group: String,

    /// The output cluster, which can differ from the changelog's.
    pub output_kafka_hosts: String,

    #[envconfig(default = "false")]
    pub output_kafka_tls: bool,

    #[envconfig(default = "clickhouse_person")]
    pub output_topic: String,

    #[envconfig(default = "personhog_changelog_relay_dlq")]
    pub dlq_topic: String,

    #[envconfig(default = "1000")]
    pub batch_size: usize,

    #[envconfig(default = "500")]
    pub batch_timeout_ms: u64,

    #[envconfig(default = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[envconfig(default = "/personhog/")]
    pub etcd_prefix: String,

    #[envconfig(default = "9106")]
    pub metrics_port: u16,
}

/// The output producer's default `message.max.bytes`, Node's WarpStream setting.
/// A rejected row goes to the DLQ as its changelog record, so this must stay
/// well above the changelog topic's limit for that copy to fit.
pub const OUTPUT_MESSAGE_MAX_BYTES: u32 = 64_000_000;

impl Config {
    pub fn output_kafka(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.output_kafka_hosts.clone(),
            kafka_tls: self.output_kafka_tls,
            kafka_producer_message_max_bytes: Some(
                self.kafka
                    .kafka_producer_message_max_bytes
                    .unwrap_or(OUTPUT_MESSAGE_MAX_BYTES),
            ),
            ..self.kafka.clone()
        }
    }

    pub fn batch_timeout(&self) -> Duration {
        Duration::from_millis(self.batch_timeout_ms)
    }

    pub fn etcd_endpoint_list(&self) -> Vec<String> {
        self.etcd_endpoints
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    #[test]
    fn the_output_producer_defaults_to_a_limit_above_any_changelog_record() {
        let cases = [
            ("unset", None, OUTPUT_MESSAGE_MAX_BYTES),
            ("overridden", Some("2000000"), 2_000_000),
        ];
        for (name, setting, expected) in cases {
            let mut env = HashMap::from([(
                "OUTPUT_KAFKA_HOSTS".to_string(),
                "localhost:9092".to_string(),
            )]);
            if let Some(value) = setting {
                env.insert(
                    "KAFKA_PRODUCER_MESSAGE_MAX_BYTES".to_string(),
                    value.to_string(),
                );
            }
            let config = Config::init_from_hashmap(&env).unwrap();
            assert_eq!(
                config.output_kafka().kafka_producer_message_max_bytes,
                Some(expected),
                "{name}"
            );
        }
    }
}
