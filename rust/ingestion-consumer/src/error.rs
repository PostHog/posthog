use thiserror::Error;

#[derive(Error, Debug)]
pub enum IngestionError {
    #[error("transport error sending to {target}: {source}")]
    Transport {
        target: String,
        source: anyhow::Error,
    },

    #[error("kafka error: {0}")]
    Kafka(#[from] rdkafka::error::KafkaError),

    #[error("serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("all retries exhausted sending to {target}")]
    RetriesExhausted { target: String },
}
