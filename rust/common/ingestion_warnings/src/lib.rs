//! Best-effort, fire-and-forget emission of ingestion warnings to Kafka.
//!
//! Two transports share the registry ([`WarningType`], generated from the
//! Node.js source of truth) and one builder ([`serializer::Warning`]):
//! services that only know API tokens (capture) commit via
//! [`serializer::Warning::into_event_envelope`], and services that know `team_id`
//! (personhog leader/writer) commit the terminal row via
//! [`serializer::Warning::into_row`]. See `serializer.rs` for the
//! field-by-field correspondence and the trust rationale.
//!
//! Envelope producers call [`WarningEmitter::emit`] with the offending
//! event's API token, a source, a registered [`WarningType`], and caller
//! context; the emitter throttles per `(token, type)`, builds a
//! `$$client_ingestion_warning` [`common_types::CapturedEvent`] envelope,
//! and enqueues it to a producer without ever awaiting delivery. Everything
//! fails open: a throttled, unserializable, or unenqueueable warning is
//! counted and dropped — the caller's hot path is never blocked or failed.
//!
//! The producer is a `common_kafka` `ThreadedProducer` (built by
//! [`common_kafka::kafka_producer::create_threaded_kafka_producer_no_ping`])
//! rather than a bespoke client: callers supply their own dedicated,
//! warnings-tuned [`common_kafka::config::KafkaConfig`] (fire-and-forget
//! acks/retries, a small queue) so warnings never share tuning or a connection
//! with a caller's main event producer. The no-ping constructor is the one that
//! matches this crate's contract — an unreachable cluster at boot must not
//! disable warnings for the process's life, let alone block the caller's
//! startup on a metadata fetch. Delivery reports are observed on the
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
pub mod request;
pub mod serializer;
pub mod test_support;
pub mod throttle;

use std::time::Duration;

use common_kafka::error::error_code_tag;
use common_kafka::kafka_producer::ThreadedKafkaContext;
use metrics::{counter, gauge};
use rdkafka::error::KafkaError;
use rdkafka::message::OwnedHeaders;
use rdkafka::producer::{BaseRecord, DeliveryResult, Producer, ThreadedProducer};
use rdkafka::types::RDKafkaErrorCode;
use serde_json::{Map, Value};
use tracing::warn;

pub use registry::WarningType;
pub use request::{emit_request_warning, WarningRequestContext, UNKNOWN_ATTRIBUTION};
pub use throttle::{ThrottleDecision, WarningThrottle};

/// Counter of emission attempts: labels `type` (warning type), `source`
/// (producing service, matches the message's `source` field), `path`
/// (metric-only, finer-grained attribution within one service), and
/// `outcome`. Enqueue-time outcomes: `emitted | throttled |
/// cardinality_capped | queue_full | serialize_error | enqueue_error`.
/// Delivery-time outcomes (reported asynchronously for each `emitted`
/// message): `delivered | delivery_failed`.
///
/// The Node.js `clientwarnings` consumer exports this same name for the rows it
/// writes, at a later stage and far higher volume. Only this side carries
/// `source`, so queries must scope by it (or by namespace) to avoid summing
/// both stages.
pub const INGESTION_WARNINGS_TOTAL: &str = "ingestion_warnings_total";

/// Counter of delivery failures by cause: labels `source`, `path`, and `error`
/// (a [`common_kafka::error::error_code_tag`] tag, shared with capture's sink
/// metrics so the two can be queried together). Separates a bad topic from an
/// unreachable broker, which `delivery_failed` alone cannot.
///
/// Its own metric because an `error` label on only one outcome of
/// [`INGESTION_WARNINGS_TOTAL`] would break aggregations over the rest.
pub const INGESTION_WARNINGS_DELIVERY_ERRORS_TOTAL: &str =
    "ingestion_warnings_delivery_errors_total";

/// Gauge of `(token, type)` keys currently tracked by the throttle, updated
/// on each sweep. The early-warning signal for the cardinality cap.
pub const INGESTION_WARNINGS_THROTTLE_KEYS: &str = "ingestion_warnings_throttle_keys";

/// Gauge reporting whether a process that *wants* an emitter actually built
/// one: `1` healthy, `0` enabled-but-failed. Deliberately unset when warnings
/// are disabled, because otherwise a misconfigured pod reporting `0` would be
/// indistinguishable from an intentionally quiet one. Absence means "off",
/// `0` means "broken".
///
/// Every emission carries a `reason` label naming the cause: `ok` when healthy,
/// otherwise the misconfiguration (capture uses `hosts_unset`, `topic_unset`,
/// `no_handle`, `producer_create_failed`). Labelling both states keeps their
/// label sets identical, so `min(...) == 0` works without aggregating it away.
///
/// Emit only after the process installs its global metrics recorder; earlier
/// `gauge!` calls are silently dropped.
///
/// `1` means the emitter was built, not that its cluster is reachable:
/// construction deliberately skips the broker ping, so a producer pointed at a
/// dead cluster still reports `1` and recovers on its own once the cluster
/// comes back. Only a genuinely unusable configuration reports `0`.
///
/// Whether warnings are actually landing is therefore a delivery question, not
/// a construction one — read the `delivered` and `delivery_failed` outcomes of
/// [`INGESTION_WARNINGS_TOTAL`] for that. Alert on `min() == 0` here to catch
/// misconfiguration, and on a sustained `delivery_failed` rate to catch a
/// broken destination.
pub const INGESTION_WARNINGS_EMITTER_ENABLED: &str = "ingestion_warnings_emitter_enabled";

/// Identifies which service — and which code path within it — produced a
/// warning.
///
/// `service` is the stable v2 message `source` field (also used as the
/// `source` metric label) and must be a value a reader of the ClickHouse
/// table can rely on; `path` is metric-only, for attributing volume to a
/// specific emit site within one service (e.g. `v1_analytics` vs `legacy`)
/// without inflating the message schema; `pipeline_step` is stamped into the
/// warning's details as `pipelineStep` — a producer-declared value, since
/// which stage a warning comes from is a property of the emit site, not of
/// the warning type.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WarningSource {
    pub service: &'static str,
    pub path: &'static str,
    pub pipeline_step: &'static str,
}

/// Capture's v1 analytics validation pipeline (`rust/capture/src/v1/analytics`).
pub const CAPTURE_V1_ANALYTICS: WarningSource = WarningSource {
    service: serializer::SOURCE_CAPTURE,
    path: "v1_analytics",
    pipeline_step: "capture_validation",
};

/// Capture's v1 analytics per-`(token, distinct_id)` rate limiter.
pub const CAPTURE_V1_RATE_LIMIT: WarningSource = WarningSource {
    service: serializer::SOURCE_CAPTURE,
    path: "v1_analytics",
    pipeline_step: "capture_rate_limit",
};

/// Capture's legacy analytics pipeline (`rust/capture/src/events/analytics.rs`),
/// per-`(token, distinct_id)` rate limiter. Split from the v1 source by `path`
/// because the two pipelines rate-limit at different points in their passes and
/// serve different deployments — the distinction is invisible in the message
/// (both are `capture`) but decides which pipeline's volume a spike belongs to.
pub const CAPTURE_LEGACY_RATE_LIMIT: WarningSource = WarningSource {
    service: serializer::SOURCE_CAPTURE,
    path: "legacy_analytics",
    pipeline_step: "capture_rate_limit",
};

/// Capture's legacy analytics validation path (`rust/capture/src/events/analytics.rs`
/// and its `v0_endpoint` caller). Unlike `CAPTURE_V1_ANALYTICS`, the legacy
/// pipeline aborts the whole request on the first invalid event, so warnings
/// from this source charge the full batch's event count rather than a per-event
/// tally.
pub const CAPTURE_LEGACY_ANALYTICS: WarningSource = WarningSource {
    service: serializer::SOURCE_CAPTURE,
    path: "legacy_analytics",
    pipeline_step: "capture_validation",
};

/// Capture's AI events endpoint (`rust/capture/src/ai_endpoint.rs`, `/i/v0/ai`).
/// One multipart event per request, so warnings from this source always carry
/// `count = 1`.
pub const CAPTURE_AI_EVENTS: WarningSource = WarningSource {
    service: serializer::SOURCE_CAPTURE,
    path: "ai_events",
    pipeline_step: "capture_validation",
};

/// Capture's OTLP trace endpoint (`rust/capture/src/otel`, `/i/v0/ai/otel`).
/// Split from `CAPTURE_AI_EVENTS` by `path` because the two AI endpoints take
/// unrelated payload formats and fail for unrelated reasons, so a spike in one
/// says nothing about the other.
pub const CAPTURE_AI_OTEL: WarningSource = WarningSource {
    service: serializer::SOURCE_CAPTURE,
    path: "ai_otel",
    pipeline_step: "capture_validation",
};

/// Capture's session replay endpoint (`rust/capture/src/events/recordings.rs`,
/// `/s`). Like `CAPTURE_LEGACY_ANALYTICS`, a validation failure aborts the whole
/// request, so warnings charge the batch's event count; unlike it, the batch was
/// on its way to becoming a single `$snapshot_items` message, so "the batch" and
/// "the message" are the same thing here. One source rather than a validation /
/// rate-limit pair because `CaptureMode::Recordings` registers no other route and
/// runs no per-distinct_id limiter.
pub const CAPTURE_REPLAY: WarningSource = WarningSource {
    service: serializer::SOURCE_CAPTURE,
    path: "replay",
    pipeline_step: "capture_validation",
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
/// (via `common_kafka::kafka_producer::create_threaded_kafka_producer_no_ping`
/// with a dedicated, fire-and-forget-tuned `KafkaConfig` and
/// [`observe_delivery`] as the delivery callback) and hand it in — this type
/// never constructs its own client. The producer's opaque is [`WarningDelivery`], so each message's
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

        let serialized = serializer::Warning::new(warning)
            .with_details(extra_details)
            .with_count(count)
            .into_event_envelope(&token, source)
            .and_then(|event| {
                serde_json::to_vec(&event).map(|payload| (payload, event.to_headers()))
            });

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

/// Metric label for a delivery failure: capture's shared [`error_code_tag`]
/// vocabulary, or `unknown` when the error carries no rdkafka code (a cancel or
/// purge during flush, for one). `&'static str`, so the poll thread never
/// allocates to label a failure.
fn delivery_error_tag(err: &KafkaError) -> &'static str {
    err.rdkafka_error_code()
        .map(error_code_tag)
        .unwrap_or("unknown")
}

/// Delivery-report callback for the warnings `ThreadedProducer`. Runs on
/// rdkafka's poll thread for every produced message and ticks the
/// `delivered`/`delivery_failed` outcome — the async half of the `emitted`
/// counter, which alone only proves the message entered the local queue.
/// Without this, a broken topic or broker at rollout looks healthy while
/// nothing lands. Failures also tick
/// [`INGESTION_WARNINGS_DELIVERY_ERRORS_TOTAL`] with the error code.
/// Metric-only (no per-message log) since a broken topic at rollout would
/// otherwise flood logs at post-throttle volume.
pub fn observe_delivery(result: &DeliveryResult, delivery: WarningDelivery) {
    let outcome = match result {
        Ok(_) => "delivered",
        Err((err, _message)) => {
            counter!(
                INGESTION_WARNINGS_DELIVERY_ERRORS_TOTAL,
                "source" => delivery.source.service,
                "path" => delivery.source.path,
                "error" => delivery_error_tag(err),
            )
            .increment(1);
            "delivery_failed"
        }
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
    use common_kafka::config::KafkaConfig;
    use common_kafka::kafka_producer::create_threaded_kafka_producer_no_ping;
    use common_liveness::SyncLivenessReporter;
    use rstest::rstest;

    use super::*;

    /// No-op liveness sink: nothing in these tests polls a broker, so there is
    /// no real health signal to report.
    #[derive(Clone, Copy)]
    struct AlwaysHealthy;

    impl SyncLivenessReporter for AlwaysHealthy {
        fn report_healthy(&self) {}
        fn report_unhealthy(&self) {}
    }

    /// Build a threaded producer against an unreachable broker (TEST-NET-1)
    /// through the same constructor production uses, so these tests exercise
    /// the real construction path and not just the right type. It returns
    /// without a broker round-trip, which is what keeps them fast and offline.
    fn unreachable_producer(
        message_timeout_ms: u32,
        linger_ms: u32,
    ) -> ThreadedProducer<ThreadedKafkaContext<WarningDelivery>> {
        let config = KafkaConfig {
            kafka_hosts: "192.0.2.1:9092".to_string(),
            kafka_message_timeout_ms: message_timeout_ms,
            kafka_producer_linger_ms: linger_ms,
            kafka_producer_queue_messages: 10,
            kafka_producer_retries: Some(0),
            ..Default::default()
        };
        create_threaded_kafka_producer_no_ping(&config, AlwaysHealthy, observe_delivery)
            .expect("client config is valid, so creation cannot fail without a broker round-trip")
    }

    // Errors reaching a delivery report don't all carry an rdkafka code. Without
    // the fallback they'd land as an empty label, merging every one of them into
    // a single anonymous series.
    #[rstest]
    #[case::has_code(
        KafkaError::MessageProduction(RDKafkaErrorCode::MessageTimedOut),
        "message_timed_out"
    )]
    #[case::carries_no_code(KafkaError::Canceled, "unknown")]
    fn delivery_error_tag_names_the_code_or_falls_back(
        #[case] err: KafkaError,
        #[case] expected: &str,
    ) {
        assert_eq!(delivery_error_tag(&err), expected);
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
