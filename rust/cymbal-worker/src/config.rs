use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

#[derive(Clone, Envconfig)]
pub struct Config {
    #[envconfig(from = "TEMPORAL_ADDRESS", default = "http://localhost:7233")]
    pub temporal_address: String,

    #[envconfig(from = "TEMPORAL_NAMESPACE", default = "default")]
    pub temporal_namespace: String,

    #[envconfig(from = "TEMPORAL_TASK_QUEUE", default = "cymbal-worker")]
    pub temporal_task_queue: String,

    #[envconfig(from = "TEMPORAL_CLIENT_IDENTITY", default = "cymbal-worker")]
    pub temporal_client_identity: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        ConsumerConfig::set_defaults("cymbal-worker", "document_embedding_results", true);

        Self::init_from_env()
    }
}
