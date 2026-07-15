//! Best-effort, fire-and-forget emission of ingestion warnings to Kafka.
//!
//! Producers (capture today; other Rust services later, see [`WarningSource`])
//! call [`WarningEmitter::emit`] with the offending event's API token, a
//! source, a registered [`WarningType`], and caller context; the emitter
//! throttles per `(token, type)`, builds a `$$client_ingestion_warning`
//! [`common_types::CapturedEvent`] envelope, and enqueues it to a producer
//! without ever awaiting delivery. Everything fails open: a throttled,
//! unserializable, or unenqueueable warning is counted and dropped — the
//! caller's hot path is never blocked or failed.
//!
//! The producer is a `common_kafka` `ThreadedProducer` (built by
//! [`common_kafka::kafka_producer::create_threaded_kafka_producer`]) rather
//! than a bespoke client: callers supply their own dedicated, warnings-tuned
//! [`common_kafka::config::KafkaConfig`] (fire-and-forget acks/retries, a
//! small queue) so warnings never share tuning or a connection with a
//! caller's main event producer. Delivery reports are observed on the
//! producer's own poll thread via [`observe_delivery`] (no per-message task);
//! `emit` attaches the warning type/source as the delivery opaque so the
//! async `delivered`/`delivery_failed` metric is attributed correctly.
//!
//! The envelope lands on the `client_ingestion_warning` topic, where the
//! Node.js `clientwarnings` consumer resolves the token to a `team_id` and
//! writes the v2 row. That keeps every Rust producer database-free and
//! identical; see [`serializer`] and
//! `nodejs/src/ingestion/common/steps/event-processing/handle-client-ingestion-warning-step.ts`.

pub mod registry;
pub mod serializer;
pub mod test_support;
pub mod throttle;

use std::time::Duration;

use chrono::Utc;
use common_kafka::kafka_producer::ThreadedKafkaContext;
use metrics::{counter, gauge};
use rdkafka::error::KafkaError;
use rdkafka::message::OwnedHeaders;
use rdkafka::producer::{BaseRecord, DeliveryResult, Producer, ThreadedProducer};
use rdkafka::types::RDKafkaErrorCode;
use serde_json::{Map, Value};
use tracing::warn;

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

/// Production emitter: per-(token, type) throttle in front of a
/// `common_kafka` `ThreadedProducer`. Callers build the producer themselves
/// (via `common_kafka::kafka_producer::create_threaded_kafka_producer` with a
/// dedicated, fire-and-forget-tuned `KafkaConfig` and [`observe_delivery`] as
/// the delivery callback) and hand it in — this type never constructs its own
/// client. The producer's opaque is [`WarningDelivery`], so each message's
/// delivery report carries the type/source needed to label the async outcome
/// metric.
pub struct KafkaWarningEmitter {
    producer: ThreadedProducer<ThreadedKafkaContext<WarningDelivery>>,
    topic: String,
    throttle: WarningThrottle,
}

impl KafkaWarningEmitter {
    pub fn new(
        producer: ThreadedProducer<ThreadedKafkaContext<WarningDelivery>>,
        topic: impl Into<String>,
    ) -> Self {
        Self {
            producer,
            topic: topic.into(),
            throttle: WarningThrottle::default(),
        }
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

        let record =
            BaseRecord::with_opaque_to(&self.topic, Box::new(WarningDelivery { warning, source }))
                .key(&token)
                .headers(headers)
                .payload(&payload);

        // `send` enqueues and returns immediately; the delivery report is
        // handled off the hot path by the producer's poll thread, which calls
        // [`observe_delivery`] via the threaded context. This is the
        // fire-and-forget shape, not `common_kafka::send_*`, which awaits
        // delivery inline.
        match self.producer.send(record) {
            Ok(()) => {
                counter!(
                    INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "source" => source.service,
                    "path" => source.path,
                    "outcome" => "emitted",
                )
                .increment(1);
            }
            Err((KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull), _record)) => {
                counter!(
                    INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "source" => source.service,
                    "path" => source.path,
                    "outcome" => "queue_full",
                )
                .increment(1);
            }
            Err((err, _record)) => {
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
        // Advisory only (shutdown path); errors are not actionable here.
        drop(self.producer.flush(timeout));
    }
}

/// Per-message opaque carried through the threaded producer to its delivery
/// callback, so each report can be attributed to the warning type and source
/// that produced it. Passed via `BaseRecord::delivery_opaque` at `emit` and
/// handed back to [`observe_delivery`] on the producer's poll thread.
#[derive(Debug, Clone, Copy)]
pub struct WarningDelivery {
    pub warning: WarningType,
    pub source: WarningSource,
}

/// Delivery-report callback for the warnings `ThreadedProducer`. Runs on
/// rdkafka's poll thread for every produced message and ticks the
/// `delivered`/`delivery_failed` outcome — the async half of the `emitted`
/// counter, which alone only proves the message entered the local queue.
/// Without this, a broken topic or broker at rollout looks healthy while
/// nothing lands. Metric-only (no per-message log) since a broken topic at
/// rollout would otherwise flood logs at post-throttle volume.
pub fn observe_delivery(result: &DeliveryResult, delivery: WarningDelivery) {
    let outcome = match result {
        Ok(_) => "delivered",
        Err(_) => "delivery_failed",
    };
    counter!(
        INGESTION_WARNINGS_TOTAL,
        "type" => delivery.warning.as_str(),
        "source" => delivery.source.service,
        "path" => delivery.source.path,
        "outcome" => outcome,
    )
    .increment(1);
}

#[cfg(test)]
mod tests {
    use common_liveness::SyncLivenessReporter;
    use rdkafka::ClientConfig;

    use super::*;

    /// No-op liveness sink: these tests build a producer directly (not via
    /// `create_kafka_producer`) specifically to skip its 15s broker-metadata
    /// ping, so there is no real health signal to report.
    #[derive(Clone, Copy)]
    struct AlwaysHealthy;

    impl SyncLivenessReporter for AlwaysHealthy {
        fn report_healthy(&self) {}
        fn report_unhealthy(&self) {}
    }

    /// Build a threaded producer against an unreachable broker (TEST-NET-1)
    /// without `create_threaded_kafka_producer`'s startup metadata fetch, so
    /// tests stay fast and offline while still exercising the exact
    /// `ThreadedProducer<ThreadedKafkaContext<WarningDelivery>>` type
    /// `KafkaWarningEmitter` holds in production. `observe_delivery` is wired
    /// as the callback, matching the production path.
    fn unreachable_producer(
        message_timeout_ms: u32,
        linger_ms: u32,
    ) -> ThreadedProducer<ThreadedKafkaContext<WarningDelivery>> {
        ClientConfig::new()
            .set("bootstrap.servers", "192.0.2.1:9092")
            .set("message.timeout.ms", message_timeout_ms.to_string())
            .set("linger.ms", linger_ms.to_string())
            .set("queue.buffering.max.messages", "10")
            .set("retries", "0")
            .create_with_context(ThreadedKafkaContext::new(AlwaysHealthy, observe_delivery))
            .expect("client config is valid, so creation cannot fail without a broker round-trip")
    }

    #[test]
    fn kafka_emitter_throttles_repeats_and_never_blocks() {
        // Unreachable broker (TEST-NET-1): emit must return instantly whether
        // the message is enqueued or throttled.
        let emitter =
            KafkaWarningEmitter::new(unreachable_producer(500, 5), "client_ingestion_warning");

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
}
