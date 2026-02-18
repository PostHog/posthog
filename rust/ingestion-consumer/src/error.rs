use thiserror::Error;

#[derive(Error, Debug)]
pub enum IngestionError {
    #[error("transport error sending to {target}: {source}")]
    Transport {
        target: String,
        source: anyhow::Error,
    },

    #[error("gRPC error sending to {target}: {status}")]
    Grpc {
        target: String,
        status: tonic::Status,
    },

    #[error("kafka error: {0}")]
    Kafka(#[from] rdkafka::error::KafkaError),

    #[error("all retries exhausted sending to {target}")]
    RetriesExhausted { target: String },
}
