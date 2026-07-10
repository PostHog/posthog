//! Best-effort, fire-and-forget emission of v2 ingestion warnings to Kafka.
//!
//! Producers (capture today; other Rust services later) call
//! [`WarningEmitter::emit`] with an API token, a registered [`WarningType`],
//! and caller context; the emitter throttles per `(token, type)`, serializes
//! the v2 message contract, and enqueues to a dedicated producer without ever
//! awaiting delivery. Everything fails open: a throttled, unserializable, or
//! unenqueueable warning is counted and dropped — the caller's hot path is
//! never blocked or failed.
//!
//! See `posthog/models/ingestion_warnings/sql_v2.py` for the consuming
//! ClickHouse stack and `nodejs/src/ingestion/common/ingestion-warnings.ts`
//! for the Node.js registry this mirrors.

pub mod producer;
pub mod registry;
pub mod serializer;
pub mod test_support;
pub mod throttle;

use std::time::Duration;

use chrono::Utc;
use metrics::counter;
use rdkafka::error::KafkaError;
use rdkafka::types::RDKafkaErrorCode;
use serde_json::{Map, Value};
use tracing::warn;

pub use producer::{WarningProducer, WarningProducerConfig};
pub use registry::WarningType;
pub use throttle::WarningThrottle;

/// Counter of emission attempts: labels `type` (warning type) and `outcome`
/// (`emitted | throttled | queue_full | serialize_error | enqueue_error`).
pub const CAPTURE_INGESTION_WARNINGS_TOTAL: &str = "capture_ingestion_warnings_total";

/// Sink-agnostic emitter seam. The Kafka implementation is
/// [`KafkaWarningEmitter`]; tests use
/// [`test_support::CollectingEmitter`].
pub trait WarningEmitter: Send + Sync {
    /// Emit one (possibly batch-deduped) warning. Synchronous and non-blocking;
    /// implementations must swallow all failures.
    ///
    /// `extra_details` carries caller context with camelCase keys
    /// (`distinctId`, `eventUuid`, `lib`, `path`, ...); `count` is the number
    /// of occurrences this message represents after per-batch dedup.
    fn emit(
        &self,
        token: &str,
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

    /// Evict fully-refilled throttle keys to bound memory. Call periodically
    /// from a maintenance task.
    pub fn sweep_throttle(&self) {
        self.throttle.sweep();
    }
}

impl WarningEmitter for KafkaWarningEmitter {
    fn emit(
        &self,
        token: &str,
        warning: WarningType,
        extra_details: Map<String, Value>,
        count: u64,
    ) {
        if !self.throttle.check(token, warning) {
            counter!(
                CAPTURE_INGESTION_WARNINGS_TOTAL,
                "type" => warning.as_str(),
                "outcome" => "throttled",
            )
            .increment(1);
            return;
        }

        let payload =
            match serializer::serialize_warning(token, warning, extra_details, count, Utc::now()) {
                Ok(payload) => payload,
                Err(err) => {
                    counter!(
                        CAPTURE_INGESTION_WARNINGS_TOTAL,
                        "type" => warning.as_str(),
                        "outcome" => "serialize_error",
                    )
                    .increment(1);
                    warn!(warning_type = warning.as_str(), error = %err,
                        "failed to serialize ingestion warning");
                    return;
                }
            };

        // Key by token so a team's warnings stay partition-local, matching
        // the Node.js producer's keying by team.
        match self.producer.send(token, &payload) {
            Ok(()) => {
                counter!(
                    CAPTURE_INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "outcome" => "emitted",
                )
                .increment(1);
            }
            Err(KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull)) => {
                counter!(
                    CAPTURE_INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "outcome" => "queue_full",
                )
                .increment(1);
            }
            Err(err) => {
                counter!(
                    CAPTURE_INGESTION_WARNINGS_TOTAL,
                    "type" => warning.as_str(),
                    "outcome" => "enqueue_error",
                )
                .increment(1);
                warn!(warning_type = warning.as_str(), error = %err,
                    "failed to enqueue ingestion warning");
            }
        }
    }

    fn flush(&self, timeout: Duration) {
        self.producer.flush(timeout);
    }
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
        emitter.emit("tok", WarningType::MissingEventName, Map::new(), 2);
        emitter.emit("tok", WarningType::MissingEventName, Map::new(), 1);
        emitter.emit("tok", WarningType::EmptyBatch, Map::new(), 5);
        assert!(
            start.elapsed() < std::time::Duration::from_millis(500),
            "emit must be fire-and-forget"
        );
    }
}
