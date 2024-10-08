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
    #[error("Reqwest error: {0}")]
    ReqwestError(#[from] reqwest::Error),
    #[error("Not implemented error: {0}")]
    NotImplementedError(String),
    #[error("Lookup failed: {0}")]
    LookupFailed(String),
    #[error("Could not get source ref from: {0}")]
    InvalidSourceRef(String),
    #[error("sourcemap error: {0}")]
    SourceMapError(#[from] sourcemap::Error),
}
