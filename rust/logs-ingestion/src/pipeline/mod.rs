//! Port of `nodejs/src/logs/pipeline/` and `logs-ingestion-consumer.ts`: the consumer on the
//! ingestion framework, with the same steps, pipeline shapes and failure semantics.

pub mod admission;
pub mod app_metrics;
pub mod buffer;
pub mod config;
pub mod consumer;
pub mod context;
pub mod deps;
pub mod errors;
pub mod finalize;
pub mod parse;
pub mod pipelines;
pub mod process;
pub mod resolve;
pub mod scenario;
pub mod types;

pub use config::LogsIngestionConsumerConfig;
pub use consumer::{BackgroundTask, LogsIngestionConsumer, ProcessedBatch};
pub use context::{AppSource, LogsConsumerIdentity, LOGS_DLQ_OUTPUT, LOGS_OUTPUT};
pub use deps::*;
pub use errors::{DependencyRetry, DependencyUnavailableError, NamedError};
pub use types::LogsIngestionMessage;
