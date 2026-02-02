//! Trait for parsing Kafka messages into domain events.

use anyhow::Result;

use crate::kafka::batch_message::KafkaMessage;

/// Trait for parsing Kafka messages into domain events.
///
/// This trait allows different pipelines to define how their
/// wire format (what comes from Kafka) is transformed into
/// the domain event type used for deduplication.
///
/// # Type Parameters
///
/// * `W` - The wire format type deserialized from Kafka (e.g., `CapturedEvent`)
/// * `E` - The domain event type used for deduplication (e.g., `RawEvent`)
pub trait EventParser<W, E> {
    /// Parse a Kafka message into a domain event.
    ///
    /// This method transforms the wire format into the domain event type,
    /// applying any necessary validation, normalization, or enrichment.
    fn parse(message: &KafkaMessage<W>) -> Result<E>;
}
