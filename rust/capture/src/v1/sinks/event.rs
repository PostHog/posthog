use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::v1::context::Context;
use crate::v1::sinks::Destination;

/// Transport-agnostic trait declaring an event's identity, routing intent,
/// metadata, and serialization. The [`Sink`](super::sink::Sink) implementation
/// resolves `destination()` to a concrete backend target using its own config.
pub trait Event: Send + Sync {
    /// Pre-parsed UUID for result correlation. Copy, zero alloc.
    fn uuid(&self) -> Uuid;

    /// Whether this event should be published. Events returning false are
    /// silently skipped by the Sink -- no `SinkResult` is returned for them.
    fn should_publish(&self) -> bool;

    /// Semantic routing destination. The Sink resolves this to a concrete
    /// backend target (e.g. Kafka topic, S3 bucket) using its own config.
    fn destination(&self) -> &Destination;

    /// Resolve the full set of transport headers for this event, using the
    /// supplied [`Context`] for batch-scoped fields (token, now,
    /// historical_migration) alongside any event-owned fields. Sinks convert
    /// the returned [`CapturedEventHeaders`] to their backend-specific format
    /// (e.g. `rdkafka::message::OwnedHeaders` via the `From` impl in
    /// `common_types`).
    fn headers(&self, ctx: &Context) -> CapturedEventHeaders;

    /// Resolve the partition key for this message, and write
    /// to the supplied buffer. Called by Sinks that write to
    /// event streams (Kafka, WarpStream etc.)
    fn write_partition_key(&self, ctx: &Context, buf: &mut String);

    /// Serialize the event payload into a caller-provided buffer.
    fn serialize_into(&self, ctx: &Context, buf: &mut String) -> anyhow::Result<()>;
}
