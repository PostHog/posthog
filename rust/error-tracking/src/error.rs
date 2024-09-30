use rdkafka::error::KafkaError;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    #[error("Config error: {0}")]
    ConfigError(#[from] envconfig::Error),
    #[error("Kafka error: {0}")]
    KafkaError(#[from] KafkaError),
    #[error("Sqlx error: {0}")]
    SqlxError(#[from] sqlx::Error),
}
