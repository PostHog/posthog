//! Best-effort, fire-and-forget emission of ingestion warnings to Kafka.
//!
//! Producers (capture today; other Rust services later, see [`WarningSource`])
//! call [`WarningEmitter::emit`] with the offending event's API token, a
//! source, a registered [`WarningType`], and caller context; the emitter
//! throttles per `(token, type)`, builds a `$$client_ingestion_warning`
//! [`common_types::CapturedEvent`] envelope, and enqueues it to a dedicated
//! producer without ever awaiting delivery. Everything fails open: a
//! throttled, unserializable, or unenqueueable warning is counted and dropped —
//! the caller's hot path is never blocked or failed.
//!
//! The envelope lands on the `client_ingestion_warning` topic, where the
//! Node.js `clientwarnings` consumer resolves the token to a `team_id` and
//! writes the v2 row. That keeps every Rust producer database-free and
//! identical; see [`serializer`] and
//! `nodejs/src/ingestion/common/steps/event-processing/handle-client-ingestion-warning-step.ts`.

pub mod producer;
pub mod registry;
pub mod serializer;
pub mod test_support;
pub mod throttle;

use std::time::Duration;

use chrono::Utc;
use metrics::{counter, gauge};
use rdkafka::error::KafkaError;
use rdkafka::message::OwnedHeaders;
use rdkafka::types::RDKafkaErrorCode;
use serde_json::{Map, Value};
use tracing::warn;

pub use producer::{WarningProducer, WarningProducerConfig};
pub use registry::WarningType;
pub use throttle::{ThrottleDecision, WarningThrottle};

/// Counter of emission attempts: labels `type` (warning type), `source`
/// (producing service, matches the message's `source` field), `path`
/// (metric-only, finer-grained attribution within one service), and
/// `outcome`. Enqueue-time outcomes: `emitted | throttled |
/// cardinality_capped | queue_full | serialize_error | enqueue_error`.
/// Delivery-time outcomes (reported asynchronously for each `emitted`
/// message): `delivered | delivery_failed`.
pub const INGESTION_WARNINGS_TOTAL: &str = "ingestion_warnings_total";

/// Gauge of `(token, type)` keys currently tracked by the throttle, updated
/// on each sweep. The early-warning signal for the cardinality cap.
pub const INGESTION_WARNINGS_THROTTLE_KEYS: &str = "ingestion_warnings_throttle_keys";

/// Identifies which service — and which code path within it — produced a
/// warning.
///
/// `service` is the stable v2 message `source` field (also used as the
/// `source` metric label) and must be a value a reader of the ClickHouse
/// table can rely on; `path` is metric-only, for attributing volume to a
/// specific emit site within one service (e.g. `v1_analytics` vs `legacy`)
/// without inflating the message schema.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WarningSource {
    pub service: &'static str,
    pub path: &'static str,
}

/// Capture's v1 analytics validation pipeline (`rust/capture/src/v1/analytics`).
pub const CAPTURE_V1_ANALYTICS: WarningSource = WarningSource {
    service: serializer::SOURCE_CAPTURE,
    path: "v1_analytics",
};

/// Sink-agnostic emitter seam. The Kafka implementation is
/// [`KafkaWarningEmitter`]; tests use
/// [`test_support::CollectingEmitter`].
pub trait WarningEmitter: Send + Sync {
    /// Emit one (possibly batch-deduped) warning. Synchronous and non-blocking;
    /// implementations must swallow all failures.
    ///
    /// `token` is the offending event's API token; the consumer resolves it to
    /// a team and it also scopes the throttle, so one token's warnings never
    /// starve another's budget. `source` identifies the producing service and
    /// code path (see [`WarningSource`]). `extra_details` carries caller
    /// context with camelCase keys (`distinctId`, `eventUuid`, `lib`, `path`,
    /// ...); `count` is the number of occurrences this message represents
    /// after per-batch dedup.
    fn emit(
        &self,
        token: String,
        source: WarningSource,
        warning: WarningType,
        extra_details: Map<String, Value>,
        count: u64,
    );

    /// Advisory drain of any buffered messages, e.g. at graceful shutdown.
    fn flush(&self, timeout: Duration);
}

/// Production emitter: per-(token, type) throttle in front of a dedicated
/// fire-and-forget Kafka producer.
pub struct KafkaWarningEmitter {
    producer: WarningProducer,
    throttle: WarningThrottle,
}

impl KafkaWarningEmitter {
    pub fn new(config: &WarningProducerConfig) -> Result<Self, KafkaError> {
        Ok(Self {
            producer: WarningProducer::new(config)?,
            throttle: WarningThrottle::default(),
        })
    }

    /// Evict fully-refilled throttle keys to bound memory and publish the
    /// tracked-key gauge. Call periodically from a maintenance task.
    pub fn sweep_throttle(&self) {
        self.throttle.sweep();
        gauge!(INGESTION_WARNINGS_THROTTLE_KEYS).set(self.throttle.tracked_keys() as f64);
    }
}

impl WarningEmitter for KafkaWarningEmitter {
    fn emit(
        &self,
        token: String,
        source: WarningSource,
        warning: WarningType,
        extra_details: Map<String, Value>,
        count: u64,
    ) {
        // Key by token so one team's warnings stay partition-local and
        // throttle-independent from every other team's, matching the Node.js
        // consumer's per-team keying downstream.
        match self.throttle.check(&token, warning) {
            ThrottleDecision::Emit => {}
            ThrottleDecision::Throttled => {
                counter!(
                    INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "source" => source.service,
                    "path" => source.path,
                    "outcome" => "throttled",
                )
                .increment(1);
                return;
            }
            ThrottleDecision::CardinalityCapped => {
                counter!(
                    INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "source" => source.service,
                    "path" => source.path,
                    "outcome" => "cardinality_capped",
                )
                .increment(1);
                return;
            }
        }

        let serialized = serializer::build_warning_event(
            &token,
            source,
            warning,
            extra_details,
            count,
            Utc::now(),
        )
        .and_then(|event| serde_json::to_vec(&event).map(|payload| (payload, event.to_headers())));

        let (payload, headers) = match serialized {
            Ok((payload, headers)) => (payload, OwnedHeaders::from(headers)),
            Err(err) => {
                counter!(
                    INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "source" => source.service,
                    "path" => source.path,
                    "outcome" => "serialize_error",
                )
                .increment(1);
                warn!(warning_type = warning.as_str(), source = source.service, error = %err,
                    "failed to serialize ingestion warning");
                return;
            }
        };

        match self.producer.send(&token, headers, &payload) {
            Ok(delivery_future) => {
                counter!(
                    INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "source" => source.service,
                    "path" => source.path,
                    "outcome" => "emitted",
                )
                .increment(1);
                spawn_delivery_observer(warning, source, delivery_future);
            }
            Err(KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull)) => {
                counter!(
                    INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "source" => source.service,
                    "path" => source.path,
                    "outcome" => "queue_full",
                )
                .increment(1);
            }
            Err(err) => {
                counter!(
                    INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "source" => source.service,
                    "path" => source.path,
                    "outcome" => "enqueue_error",
                )
                .increment(1);
                warn!(warning_type = warning.as_str(), source = source.service, error = %err,
                    "failed to enqueue ingestion warning");
            }
        }
    }

    fn flush(&self, timeout: Duration) {
        self.producer.flush(timeout);
    }
}

/// Observe a message's delivery report off the hot path. `emitted` only
/// proves the message entered the local queue; without this, a broken topic
/// or broker at rollout looks healthy while nothing lands. Post-throttle
/// volume is tiny (≤ affected tokens × types per pod per hour), so one
/// detached task per message is cheap. Outside a tokio runtime (sync tests,
/// exotic embedders) the future is dropped and delivery stays unobserved —
/// never an error.
fn spawn_delivery_observer(
    warning: WarningType,
    source: WarningSource,
    delivery_future: rdkafka::producer::DeliveryFuture,
) {
    let Ok(handle) = tokio::runtime::Handle::try_current() else {
        return;
    };
    handle.spawn(async move {
        // Delivery outcome is reported via the `delivery_failed` metric tag
        // only — no per-message log line, since a broken topic at rollout
        // would otherwise flood logs at post-throttle volume.
        let outcome = match delivery_future.await {
            Ok(Ok(_partition_offset)) => "delivered",
            Ok(Err(_)) => "delivery_failed",
            // Producer dropped before the report arrived (shutdown).
            Err(_canceled) => "delivery_failed",
        };
        counter!(
            INGESTION_WARNINGS_TOTAL,
            "type" => warning.as_str(),
            "source" => source.service,
            "path" => source.path,
            "outcome" => outcome,
        )
        .increment(1);
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kafka_emitter_throttles_repeats_and_never_blocks() {
        // Unreachable broker (TEST-NET-1): emit must return instantly whether
        // the message is enqueued or throttled.
        let emitter = KafkaWarningEmitter::new(&WarningProducerConfig {
            kafka_hosts: "192.0.2.1:9092".to_string(),
            ..WarningProducerConfig::default()
        })
        .unwrap();

        let start = std::time::Instant::now();
        emitter.emit(
            "tok".to_string(),
            CAPTURE_V1_ANALYTICS,
            WarningType::MissingEventName,
            Map::new(),
            2,
        );
        emitter.emit(
            "tok".to_string(),
            CAPTURE_V1_ANALYTICS,
            WarningType::MissingEventName,
            Map::new(),
            1,
        );
        emitter.emit(
            "tok".to_string(),
            CAPTURE_V1_ANALYTICS,
            WarningType::EmptyBatch,
            Map::new(),
            5,
        );
        assert!(
            start.elapsed() < std::time::Duration::from_millis(500),
            "emit must be fire-and-forget"
        );
    }

    #[tokio::test]
    async fn emit_inside_a_runtime_spawns_delivery_observer_without_blocking() {
        // Same unreachable broker, but inside a tokio runtime so the delivery
        // observer task actually spawns; emit must still return immediately.
        let emitter = KafkaWarningEmitter::new(&WarningProducerConfig {
            kafka_hosts: "192.0.2.1:9092".to_string(),
            message_timeout_ms: 500,
            linger_ms: 5,
            ..WarningProducerConfig::default()
        })
        .unwrap();

        let start = std::time::Instant::now();
        emitter.emit(
            "tok".to_string(),
            CAPTURE_V1_ANALYTICS,
            WarningType::MissingEventName,
            Map::new(),
            1,
        );
        assert!(
            start.elapsed() < std::time::Duration::from_millis(500),
            "emit must not await the delivery report"
        );
    }
}
