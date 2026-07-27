use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::v1::context::RequestContext;
use crate::v1::sinks::Destination;

/// Transport-agnostic trait declaring an event's identity, routing intent,
/// metadata, and serialization. The [`Sink`](super::sink::Sink) implementation
/// resolves `destination()` to a concrete backend target using its own config.
pub trait Event: Send + Sync {
    /// Pre-parsed UUID for result correlation.
    fn uuid(&self) -> Uuid;

    /// Whether this event should be published. Events returning false are
    /// silently skipped by the Sink -- no `SinkResult` is returned for them.
    fn should_publish(&self) -> bool;

    /// Semantic routing destination. The Sink resolves this to a concrete
    /// backend target (e.g. Kafka topic, S3 bucket) using its own config.
    fn destination(&self) -> &Destination;

    /// Resolve the full set of transport headers for this event, using the
    /// supplied [`RequestContext`] for batch-scoped fields (token, now,
    /// historical_migration) alongside any event-owned fields. Sinks convert
    /// the returned [`CapturedEventHeaders`] to their backend-specific format
    /// (e.g. `rdkafka::message::OwnedHeaders` via the `From` impl in
    /// `common_types`).
    fn headers(&self, ctx: &RequestContext) -> CapturedEventHeaders;

    /// Return the partition key for this event.
    /// The sink decides whether to use it or null it based on routing policy
    /// (e.g. force_disable_person_processing).
    fn partition_key(&self, ctx: &RequestContext) -> String;

    /// Serialize the event payload and return the raw bytes. `Bytes` (not
    /// `String`) so non-UTF-8 / binary payloads (e.g. replay) share this
    /// contract, and so a serialized payload can be cheaply cloned across
    /// multiple sinks (dual-write) without re-encoding.
    fn serialize(&self, ctx: &RequestContext) -> anyhow::Result<bytes::Bytes>;
}
