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

impl Config {
    pub fn output_kafka(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.output_kafka_hosts.clone(),
            kafka_tls: self.output_kafka_tls,
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
