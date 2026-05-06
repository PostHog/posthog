pub mod config;
pub mod context;
pub mod mock;
pub mod producer;
pub mod sink;
pub mod types;

#[cfg(test)]
mod sink_tests;

pub use sink::KafkaSink;

use std::future::Future;
use std::time::Duration;

use rdkafka::error::KafkaError;

use crate::v1::sinks::SinkName;
use producer::{ProduceError, ProduceRecord};

/// Trait abstracting a Kafka producer for testability.
/// `KafkaProducer` is the real impl; `MockProducer` is the test impl.
pub trait KafkaProducerTrait: Send + Sync {
    type Ack: Future<Output = Result<(), ProduceError>> + Send;

    fn send<'a>(
        &self,
        record: ProduceRecord<'a>,
    ) -> Result<Self::Ack, (ProduceError, ProduceRecord<'a>)>;
    fn flush(&self, timeout: Duration) -> Result<(), KafkaError>;
    fn is_ready(&self) -> bool;
    fn sink_name(&self) -> SinkName;
}
