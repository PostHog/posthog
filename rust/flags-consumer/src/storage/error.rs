use thiserror::Error;

#[derive(Error, Debug)]
pub enum CdcError {
    #[error("database error: {0}")]
    Database(#[from] sqlx::Error),

    #[error("kafka error: {0}")]
    Kafka(String),

    #[error("retries exhausted after {attempts} attempts: {source}")]
    RetriesExhausted { attempts: u32, source: sqlx::Error },
}
