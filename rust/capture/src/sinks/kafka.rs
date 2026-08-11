//! Kafka sink (mechanism layer).
//!
//! This sink is pure mechanism: it serializes `ProcessedEvent`s and produces them
//! to Kafka using `rdkafka`. All routing *policy* (overflow rerouting, DLQ
//! redirects, custom-topic redirects, force-disable-person-processing headers) is
//! decided *upstream* in the pipeline and stamped onto
//! `ProcessedEventMetadata`. `KafkaSinkBase::prepare_record` reads that metadata
//! and maps it to a concrete topic + partition key.
//!
//! The `overflow_reason` stamping specifically runs at four call sites, all via
//! the shared `events::overflow_stamping::stamp_overflow_reason` helper:
//! * `events::analytics::process_events` (analytics batch path: `/e/`, `/batch/`, `/capture`, etc.)
//! * `events::recordings::process_replay_events` (replay-specific `RedisLimiter`, stamps `OverflowReason::ReplayLimited`)
//! * `ai_endpoint::ai_handler` (`/i/v0/ai`, single-event)
//! * `otel::otel_handler` (`/i/v0/ai/otel`, multi-span batch)
//!
//! Keeping routing policy out of the sink keeps the clone-per-spawned-task
//! cost in the scatter-gather batch path at two `Arc::clone` calls (producer
//! + topics) rather than deep copies of limiter state.
use crate::api::CaptureError;
use crate::config::{EnvelopeCompression, KafkaConfig};
use crate::ordering::OrderingGuarantee;
use crate::outputs::Prepare;
use crate::pipeline::{self, Address, Lane, Pipeline};
use crate::serialization::Serializer;
use crate::sinks::producer::{KafkaProducer, ProduceRecord};
use crate::sinks::registry::{Output, OutputRegistry};
use crate::sinks::sink::{fold_results, Outcome, PreparedPayload, Sink, SinkResult};
use crate::sinks::Event;
use crate::v0_request::{DataType, ProcessedEvent};
use async_trait::async_trait;
use metrics::{counter, gauge, histogram};
use rdkafka::producer::{FutureProducer, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::task::JoinSet;
use tracing::log::{debug, error, info};
use tracing::{info_span, instrument, Instrument};

use super::producer::RdKafkaProducer;

pub struct KafkaContext {
    /// Lifecycle handle this producer reports liveness to. `None` for a producer
    /// whose health must not gate the pod — it still produces and emits
    /// metrics, it just doesn't drive a manager component.
    liveness: Option<lifecycle::Handle>,
}

/// Emit min/avg/max/stddev plus p50/p90/p95/p99 for an rdkafka window stat
/// (rtt, int_latency, outbuf_latency). Gauges are tagged with `quantile` and
/// `broker` so existing dashboards keyed on `quantile` keep working and new
/// panels can pick up `max`/`avg` for tail visibility.
fn emit_window_stats(
    metric_name: &'static str,
    window: &rdkafka::statistics::Window,
    broker: &str,
) {
    for (quantile, value) in [
        ("min", window.min),
        ("avg", window.avg),
        ("max", window.max),
        ("stddev", window.stddev),
        ("p50", window.p50),
        ("p90", window.p90),
        ("p95", window.p95),
        ("p99", window.p99),
    ] {
        gauge!(
            metric_name,
            "quantile" => quantile,
            "broker" => broker.to_string()
        )
        .set(value as f64);
    }
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, stats: rdkafka::Statistics) {
        // Signal liveness when brokers are up
        let brokers_up = stats.brokers.values().any(|broker| broker.state == "UP");
        if brokers_up {
            if let Some(liveness) = &self.liveness {
                liveness.report_healthy();
            }
        }

        let total_brokers = stats.brokers.len();
        let up_brokers = stats
            .brokers
            .values()
            .filter(|broker| broker.state == "UP")
            .count();
        let down_brokers = total_brokers.saturating_sub(up_brokers);
        gauge!("capture_kafka_any_brokers_down").set(if down_brokers > 0 { 1.0 } else { 0.0 });

        // Update exported metrics
        gauge!("capture_kafka_callback_queue_depth",).set(stats.replyq as f64);
        gauge!("capture_kafka_producer_queue_depth",).set(stats.msg_cnt as f64);
        gauge!("capture_kafka_producer_queue_depth_limit",).set(stats.msg_max as f64);
        gauge!("capture_kafka_producer_queue_bytes",).set(stats.msg_size as f64);
        gauge!("capture_kafka_producer_queue_bytes_limit",).set(stats.msg_size_max as f64);

        for (topic, stats) in stats.topics {
            gauge!(
                "capture_kafka_produce_avg_batch_size_bytes",
                "topic" => topic.clone()
            )
            .set(stats.batchsize.avg as f64);
            gauge!(
                "capture_kafka_produce_avg_batch_size_events",
                "topic" => topic
            )
            .set(stats.batchcnt.avg as f64);
        }

        for (_, stats) in stats.brokers {
            let id_string = format!("{}", stats.nodeid);

            // Per-broker connectivity (1 = connected/UP, 0 = not connected)
            gauge!(
                "capture_kafka_broker_connected",
                "broker" => id_string.clone()
            )
            .set(if stats.state == "UP" { 1.0 } else { 0.0 });
            if let Some(rtt) = stats.rtt {
                emit_window_stats("capture_kafka_produce_rtt_latency_us", &rtt, &id_string);
            }
            // Time messages spent in the producer's internal queue (linger + backlog).
            // Usually the dominant source of long-tail ack delays when brokers are slow.
            if let Some(int_latency) = stats.int_latency {
                emit_window_stats(
                    "capture_kafka_produce_int_latency_us",
                    &int_latency,
                    &id_string,
                );
            }
            // Time requests spent in the broker's output buffer before going on the wire.
            if let Some(outbuf_latency) = stats.outbuf_latency {
                emit_window_stats(
                    "capture_kafka_produce_outbuf_latency_us",
                    &outbuf_latency,
                    &id_string,
                );
            }

            gauge!(
                "capture_kafka_broker_requests_pending",
                "broker" => id_string.clone()
            )
            .set(stats.outbuf_cnt as f64);
            gauge!(
                "capture_kafka_broker_responses_awaiting",
                "broker" => id_string.clone()
            )
            .set(stats.waitresp_cnt as f64);
            counter!(
                "capture_kafka_broker_tx_errors_total",
                "broker" => id_string.clone()
            )
            .absolute(stats.txerrs);
            counter!(
                "capture_kafka_broker_rx_errors_total",
                "broker" => id_string.clone()
            )
            .absolute(stats.rxerrs);
            counter!(
                "capture_kafka_broker_request_timeouts",
                "broker" => id_string
            )
            .absolute(stats.req_timeouts);
        }
    }
}

/// Generic Kafka sink that can use any producer implementation.
///
/// Holds only the producer handle, the topic config, and the replay envelope
/// compression setting. No limiter state — overflow and replay-overflow routing
/// decisions are stamped upstream in the pipeline onto
/// `ProcessedEventMetadata::overflow_reason` and read here.
/// Both Arc fields are cheap to clone (two atomic ref-count increments),
/// which matters under the scatter-gather batch produce path where the sink
/// is cloned once per spawned prep task.
pub struct KafkaSinkBase<P: KafkaProducer> {
    producer: Arc<P>,
    topics: Arc<OutputRegistry>,
    replay_envelope_compression: EnvelopeCompression,
}

impl<P: KafkaProducer> Clone for KafkaSinkBase<P> {
    fn clone(&self) -> Self {
        Self {
            producer: Arc::clone(&self.producer),
            topics: Arc::clone(&self.topics),
            replay_envelope_compression: self.replay_envelope_compression,
        }
    }
}

/// Map a lane address to the sink's configured [`Output`]. The sink owns
/// this mapping only until the outputs layer exists to own the address →
/// output table. Every `(pipeline, lane)` pair is spelled out so that a new
/// lane, or a change making an unbacked pair reachable, has to visit this
/// match instead of being absorbed by a wildcard. `None` marks a pair
/// [`pipeline::resolve`] never produces — no output backs it, and the caller
/// dlqs the event (the typed-per-pipeline-lanes step makes these pairs
/// unrepresentable).
fn lane_output(pipeline: Pipeline, lane: Lane) -> Option<Output> {
    match (pipeline, lane) {
        (Pipeline::Analytics, Lane::Main) => Some(Output::AnalyticsMain),
        (Pipeline::Analytics, Lane::Overflow) => Some(Output::AnalyticsOverflow),
        (Pipeline::Analytics, Lane::Historical) => Some(Output::AnalyticsHistorical),
        (Pipeline::Ai, Lane::Main) => Some(Output::AiMain),
        (Pipeline::Ai, Lane::Overflow) => Some(Output::AiOverflow),
        (Pipeline::Ai, Lane::Historical) => None,
        (Pipeline::Warnings, Lane::Main) => Some(Output::ClientWarningsMain),
        (Pipeline::Warnings, Lane::Overflow | Lane::Historical) => None,
        (Pipeline::Heatmaps, Lane::Main) => Some(Output::HeatmapsMain),
        (Pipeline::Heatmaps, Lane::Overflow | Lane::Historical) => None,
        (Pipeline::ErrorTracking, Lane::Main) => Some(Output::ErrorTrackingMain),
        (Pipeline::ErrorTracking, Lane::Overflow | Lane::Historical) => None,
        (Pipeline::Replay, Lane::Main) => Some(Output::SessionReplayMain),
        (Pipeline::Replay, Lane::Overflow) => Some(Output::SessionReplayOverflow),
        (Pipeline::Replay, Lane::Historical) => None,
    }
}

/// The dlq output's contract: count the reroute and stamp the dlq header set.
fn dlq_reroute_effects(headers: &mut common_types::CapturedEventHeaders, reason: &'static str) {
    counter!("capture_events_rerouted_dlq", &[("reason", reason)]).increment(1);

    headers.set_dlq_reason(reason.to_string());
    // Unlike with our node code, DLQ step will always be static.
    headers.set_dlq_step("capture".to_string());
    headers
        .set_dlq_timestamp(chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true));
}

/// The default KafkaSink using rdkafka's FutureProducer
pub type KafkaSink = KafkaSinkBase<RdKafkaProducer<KafkaContext>>;

impl KafkaSink {
    pub async fn new(
        config: KafkaConfig,
        liveness: Option<lifecycle::Handle>,
    ) -> anyhow::Result<KafkaSink> {
        // Refuse to boot on incomplete output wiring: a blank topic fails
        // here, at startup, instead of at first produce. Config-only, so it
        // runs before the producer is built and the broker is pinged — the
        // refusal is instant, not one connect attempt later.
        let registry = OutputRegistry::from(&config);
        if config.outputs_completeness_check_enabled {
            registry.check_complete()?;
        } else {
            info!("outputs completeness check disabled; a blank output topic will fail at first produce instead of at boot");
        }

        info!("connecting to Kafka brokers at {}...", config.kafka_hosts);

        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("partitioner", &config.kafka_producer_partitioner)
            .set(
                "metadata.max.age.ms",
                config.kafka_metadata_max_age_ms.to_string(),
            )
            .set(
                "topic.metadata.refresh.interval.ms",
                config.kafka_topic_metadata_refresh_interval_ms.to_string(),
            )
            .set(
                "message.send.max.retries",
                config.kafka_producer_max_retries.to_string(),
            )
            .set("linger.ms", config.kafka_producer_linger_ms.to_string())
            .set(
                "message.max.bytes",
                config.kafka_producer_message_max_bytes.to_string(),
            )
            .set(
                "message.timeout.ms",
                config.kafka_message_timeout_ms.to_string(),
            )
            .set(
                "socket.timeout.ms",
                config.kafka_socket_timeout_ms.to_string(),
            )
            .set("compression.codec", &config.kafka_compression_codec)
            .set(
                "queue.buffering.max.kbytes",
                (config.kafka_producer_queue_mib * 1024).to_string(),
            )
            .set("acks", &config.kafka_producer_acks)
            .set(
                "batch.num.messages",
                config.kafka_producer_batch_num_messages.to_string(),
            )
            .set("batch.size", config.kafka_producer_batch_size.to_string())
            .set(
                "max.in.flight.requests.per.connection",
                config.kafka_producer_max_in_flight_requests.to_string(),
            )
            .set(
                "sticky.partitioning.linger.ms",
                config
                    .kafka_producer_sticky_partitioning_linger_ms
                    .to_string(),
            )
            .set(
                "enable.idempotence",
                config.kafka_producer_enable_idempotence.to_string(),
            )
            .set(
                "log.connection.close",
                config.kafka_log_connection_close.to_string(),
            )
            .set(
                "queue.buffering.max.messages",
                config
                    .kafka_producer_queue_buffering_max_messages
                    .to_string(),
            )
            .set(
                "retry.backoff.max.ms",
                config.kafka_retry_backoff_max_ms.to_string(),
            )
            .set(
                "socket.send.buffer.bytes",
                config.kafka_socket_send_buffer_bytes.to_string(),
            )
            .set(
                "socket.receive.buffer.bytes",
                config.kafka_socket_receive_buffer_bytes.to_string(),
            );

        if !config.kafka_broker_address_family.is_empty() {
            client_config.set("broker.address.family", &config.kafka_broker_address_family);
        }

        if !&config.kafka_client_id.is_empty() {
            client_config.set("client.id", &config.kafka_client_id);
        }

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        debug!("rdkafka configuration: {client_config:?}");

        let producer: FutureProducer<KafkaContext> =
            client_config.create_with_context(KafkaContext {
                liveness: liveness.clone(),
            })?;

        // Ping the cluster to make sure we can reach brokers, fail after 10 seconds
        // Note: we don't error if we fail to connect as there may be other sinks that report healthy
        if producer
            .client()
            .fetch_metadata(
                Some("__consumer_offsets"),
                Timeout::After(Duration::new(10, 0)),
            )
            .is_ok()
        {
            if let Some(liveness) = &liveness {
                liveness.report_healthy();
            }
            info!("connected to Kafka brokers");
        };

        let topics = Arc::new(registry);
        let rd_producer = RdKafkaProducer::new(producer);

        Ok(KafkaSinkBase {
            producer: Arc::new(rd_producer),
            topics,
            replay_envelope_compression: config.kafka_replay_envelope_compression,
        })
    }
}

impl<P: KafkaProducer> KafkaSinkBase<P> {
    /// Create a new KafkaSinkBase with a custom producer (useful for testing).
    /// No limiters — the sink is a mechanism layer; overflow stamping happens
    /// upstream in the pipeline. See the module header for details.
    pub fn with_producer(producer: P, topics: OutputRegistry) -> Self {
        Self {
            producer: Arc::new(producer),
            topics: Arc::new(topics),
            replay_envelope_compression: EnvelopeCompression::None,
        }
    }

    /// Same as `with_producer` but with envelope compression enabled. Used in tests.
    pub fn with_producer_and_compression(
        producer: P,
        topics: OutputRegistry,
        replay_envelope_compression: EnvelopeCompression,
    ) -> Self {
        Self {
            producer: Arc::new(producer),
            topics: Arc::new(topics),
            replay_envelope_compression,
        }
    }

    /// CPU-bound prep work: serialize payload + build headers + pick topic/key.
    /// Safe to run concurrently across events in a batch because it does not
    /// touch the librdkafka producer queue — `Sink::publish` is what enforces
    /// per-partition ordering by calling `enqueue_record` serially in the
    /// original event order.
    ///
    /// Routing policy is read from `ProcessedEventMetadata` (stamped upstream
    /// by the pipeline). This function does not consult any limiter — it is
    /// pure mechanism. DLQ and custom-topic redirects take priority over
    /// overflow routing.
    ///
    /// Prep lives in this file rather than the outputs layer because it
    /// reads state the sink still owns (the topic registry, the replay
    /// envelope setting). Keeping it off the `Sink` trait is what matters
    /// for the layering: callers above can prep and publish as separate
    /// phases. The prep hoist (step 12 of
    /// `rust/capture/OUTPUTS_REFACTOR_PLAN.md`) moves the assembly and that
    /// state up; drop this note when it lands.
    ///
    /// Not `async`: there are no await points, and keeping it
    /// synchronous lets `prepare_batch`'s serial fast path call it inline
    /// without any runtime indirection.
    fn prepare_record(&self, event: ProcessedEvent) -> Result<PreparedPayload, CaptureError> {
        let (event, metadata) = (event.event, event.metadata);
        let uuid = event.uuid;

        // Encoding is resolved by data_type, not by the routed destination:
        // session replay gets the lz4 envelope when configured, everything
        // else the plain JSON contract — so a replay event redirected to the
        // DLQ or a custom topic keeps the envelope, with its content-encoding
        // header travelling along. See `crate::serialization` for the formats,
        // the envelope byte layout, and the coexistence story.
        let serializer = match (metadata.data_type, self.replay_envelope_compression) {
            (DataType::SnapshotMain, EnvelopeCompression::Lz4) => Serializer::JSON_LZ4,
            _ => Serializer::JSON,
        };
        let payload = serializer.serialize(&event).map_err(|e| {
            error!(
                "failed to serialize {} event payload: {e:#}",
                metadata.event_name
            );
            CaptureError::NonRetryableSinkError
        })?;

        let event_key = event.key();

        // Use the event's to_headers() method for consistent header serialization
        let mut headers = event.to_headers();

        drop(event); // Events can be EXTREMELY memory hungry

        // The stamped flag (event restrictions / upstream decisions) or a
        // ForceLimited reason, which implies the skip on its own.
        if metadata.person_processing_disabled() {
            headers.set_force_disable_person_processing(true);
        }

        if metadata.skip_heatmap_processing {
            headers.set_skip_heatmap_processing(true);
        }

        // The address decision is pure metadata policy, owned by the pipeline
        // layer; the sink bridges it to an output, resolves that against its
        // topic config, realizes the key policy against the values it owns,
        // and applies the address-implied side effects in the same match —
        // the dlq output's contract includes the dlq header set, and both
        // admin redirects count their reroutes.
        let decision = pipeline::resolve(&metadata, self.topics.ai_events_overflow_armed())?;
        let target = match decision.address {
            Address::Dlq => {
                dlq_reroute_effects(&mut headers, "event_restriction");
                Output::Dlq
            }
            Address::Custom(topic) => {
                counter!(
                    "capture_events_rerouted_custom_topic",
                    &[("reason", "event_restriction")]
                )
                .increment(1);
                Output::Custom(topic)
            }
            Address::Lane { pipeline, lane } => match lane_output(pipeline, lane) {
                Some(output) => output,
                // A pair `resolve` never produces: no output backs it, so
                // the event goes to the dlq — preserved and replayable —
                // instead of being processed through a lane with the wrong
                // semantics. Loud, because reaching this arm means a change
                // made the pair producible without giving it an output.
                None => {
                    debug_assert!(false, "no output backs ({pipeline:?}, {lane:?})");
                    error!("no output backs ({pipeline:?}, {lane:?}), publishing to the dlq");
                    dlq_reroute_effects(&mut headers, "unbacked_lane");
                    Output::Dlq
                }
            },
        };

        let destination = self.topics.topic_for(&target).to_string();

        let partition_key = match decision.ordering {
            // resolve() rejects replay events without a session id, so the id
            // is present whenever PerSession is decided.
            OrderingGuarantee::PerSession => {
                metadata.session_id.ok_or(CaptureError::MissingSessionId)?
            }
            OrderingGuarantee::PerDistinctId | OrderingGuarantee::None => event_key,
        };

        if let Some(encoding) = serializer.content_encoding() {
            headers.set_content_encoding(encoding.to_string());
        }

        Ok(PreparedPayload {
            uuid,
            destination,
            partition_key,
            ordering: decision.ordering,
            payload,
            headers,
        })
    }

    /// Serial, ordering-preserving enqueue into librdkafka. The one place the
    /// backend-agnostic payload becomes Kafka-shaped: `destination` is the
    /// topic, and `ordering` decides whether the record is keyed. Emits the
    /// per-topic bytes counter and returns the ack future for the caller to
    /// await. librdkafka preserves on-wire partition order by `send_result`
    /// call order, so this MUST be called in the original event order within
    /// a batch.
    fn enqueue_record(&self, payload: PreparedPayload) -> Result<P::AckFuture, CaptureError> {
        counter!("capture_kafka_produce_bytes_total", "topic" => payload.destination.clone())
            .increment(payload.payload.len() as u64);

        // No key reaches rdkafka as round-robin; `Some("")` would murmur2-hash
        // every record onto one deterministic hot partition.
        let key = match payload.ordering {
            OrderingGuarantee::None => None,
            _ => Some(payload.partition_key),
        };

        self.producer.send(ProduceRecord {
            topic: payload.destination,
            key,
            payload: payload.payload,
            headers: payload.headers,
        })
    }

    /// Prep + enqueue for the single-event path. Retained as a thin wrapper so
    /// the `Event::send` impl stays unchanged; the batch path runs the same
    /// pieces through `prepare_batch` and `Sink::publish`.
    fn kafka_send(&self, event: ProcessedEvent) -> Result<P::AckFuture, CaptureError> {
        let payload = self.prepare_record(event)?;
        self.enqueue_record(payload)
    }
}

/// Batches below this size take the serial fast path in `prepare_batch`:
/// spawning N `JoinSet` tasks to run `prepare_record` in parallel is
/// net-negative when each task does only a `serde_json::to_string` and a
/// header build — the scheduler overhead dominates the CPU savings.
/// Scatter-gather kicks in at or above this threshold where parallel prep
/// wins back its spawn cost.
pub(crate) const SCATTER_GATHER_MIN_BATCH: usize = 8;

impl<P: KafkaProducer + 'static> KafkaSinkBase<P> {
    /// CPU-bound batch prep: run `prepare_record` over the batch and return
    /// the payloads in the original event order, fail-fast on the first prep
    /// error so no partially-prepped batch reaches the producer. Inherent
    /// rather than on the `Sink` trait: payload assembly is not backend
    /// mechanism, and the outputs layer becomes its caller.
    pub(crate) async fn prepare_batch(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<PreparedPayload>, CaptureError> {
        let batch_size = events.len();

        // Small-batch fast path. For batches under `SCATTER_GATHER_MIN_BATCH`
        // the JoinSet spawn overhead dominates any parallel-prep win, so we
        // stay single-threaded. Both paths share the semantic "prep error ->
        // no records produced": all events prep before anything is enqueued.
        // The duration histogram is recorded on every exit so dashboards
        // keep a faithful view of the fast path.
        if batch_size < SCATTER_GATHER_MIN_BATCH {
            let prep_start = Instant::now();
            let mut prepared: Vec<PreparedPayload> = Vec::with_capacity(batch_size);
            for event in events {
                match self.prepare_record(event) {
                    Ok(payload) => prepared.push(payload),
                    Err(err) => {
                        histogram!("capture_kafka_batch_prep_duration_seconds")
                            .record(prep_start.elapsed().as_secs_f64());
                        return Err(err);
                    }
                }
            }
            histogram!("capture_kafka_batch_prep_duration_seconds")
                .record(prep_start.elapsed().as_secs_f64());
            return Ok(prepared);
        }

        // Parallel prep across tokio workers. Each task returns its input
        // index so we can reassemble results in the original event order
        // before the serial enqueue phase. This is where the CPU win lives:
        // serde_json::to_string + header build run concurrently on up to N
        // worker threads, rather than sequentially on a single task.
        let prep_start = Instant::now();
        let mut prep_set: JoinSet<(usize, Result<PreparedPayload, CaptureError>)> = JoinSet::new();
        for (idx, event) in events.into_iter().enumerate() {
            let this = self.clone();
            prep_set.spawn(
                async move { (idx, this.prepare_record(event)) }
                    .instrument(info_span!("prepare_record")),
            );
        }

        // Collect into a (idx, payload) Vec and sort rather than indexing into
        // a `Vec<Option<PreparedPayload>>`. Encodes the "every slot filled"
        // invariant in the type: no `Option`, no unreachable `expect`, no
        // N-element `None` preallocation. Our only cancellation source is
        // `prep_set.abort_all()` below, invoked only from an already-errored
        // branch, so any `JoinError` observed during normal drain implies a
        // panic inside `prepare_record` — counted separately so it's alertable.
        let mut prepared: Vec<(usize, PreparedPayload)> = Vec::with_capacity(batch_size);
        while let Some(join_result) = prep_set.join_next().await {
            let (idx, result) = match join_result {
                Err(err) => {
                    counter!("capture_kafka_prep_panic_total").increment(1);
                    error!("join error while preparing Kafka record: {err:#}");
                    // Drain remaining prep tasks before returning so they can't
                    // leak records into librdkafka after we've already failed.
                    // Record the histogram on the error path too so prep-duration
                    // stays observable during failures (not just happy path).
                    prep_set.abort_all();
                    histogram!("capture_kafka_batch_prep_duration_seconds")
                        .record(prep_start.elapsed().as_secs_f64());
                    return Err(CaptureError::RetryableSinkError);
                }
                Ok(inner) => inner,
            };
            match result {
                Ok(payload) => prepared.push((idx, payload)),
                Err(err) => {
                    prep_set.abort_all();
                    histogram!("capture_kafka_batch_prep_duration_seconds")
                        .record(prep_start.elapsed().as_secs_f64());
                    return Err(err);
                }
            }
        }
        prepared.sort_unstable_by_key(|(idx, _)| *idx);
        debug_assert_eq!(prepared.len(), batch_size);
        histogram!("capture_kafka_batch_prep_duration_seconds")
            .record(prep_start.elapsed().as_secs_f64());

        Ok(prepared.into_iter().map(|(_, payload)| payload).collect())
    }
}

#[async_trait]
impl<P: KafkaProducer + 'static> Sink for KafkaSinkBase<P> {
    /// Serial enqueue in payload order + fail-fast ack drain. The serial
    /// enqueue is the ordering bottleneck we deliberately keep: librdkafka
    /// preserves per-partition on-wire order by send_result() call order, and
    /// same-distinct_id events hash to the same partition via murmur2.
    /// Within-batch same-key ordering must survive so e.g. $identify lands
    /// before subsequent events.
    ///
    /// Results are batch-uniform: the whole batch reports the first failure,
    /// acked-before-failure events included. The per-event surface refines
    /// only with the per-event response model.
    async fn publish(&self, payloads: Vec<PreparedPayload>) -> Vec<SinkResult> {
        // Results are built in payload order as the loop enqueues, so the one
        // Vec the return type requires is the only allocation on the happy
        // path. Failure paths rewrite it in place to the batch-uniform error.
        let mut results: Vec<SinkResult> = Vec::with_capacity(payloads.len());

        let enqueue_start = Instant::now();
        let mut ack_set = JoinSet::new();
        let mut payloads = payloads.into_iter();
        for payload in payloads.by_ref() {
            let uuid = payload.uuid;
            match self.enqueue_record(payload) {
                Ok(ack_future) => {
                    ack_set.spawn(ack_future);
                    results.push(SinkResult::published(uuid));
                }
                Err(err) => {
                    // Record enqueue duration on the error path too so slow-fail
                    // cases (e.g. QueueFull after a long stall) stay observable.
                    // Dropping `ack_set` aborts any already spawned ack futures
                    // for this batch; DeliveryAckFuture::drop then records the
                    // "dropped" outcome on capture_kafka_produce_ack_duration_ms.
                    histogram!("capture_kafka_batch_enqueue_duration_seconds")
                        .record(enqueue_start.elapsed().as_secs_f64());
                    for result in &mut results {
                        result.outcome = Outcome::Failed(err.clone());
                    }
                    results.push(SinkResult::failed(uuid, err.clone()));
                    results.extend(payloads.map(|p| SinkResult::failed(p.uuid, err.clone())));
                    return results;
                }
            }
        }
        histogram!("capture_kafka_batch_enqueue_duration_seconds")
            .record(enqueue_start.elapsed().as_secs_f64());

        match drain_acks(ack_set).await {
            Ok(()) => results,
            Err(err) => {
                for result in &mut results {
                    result.outcome = Outcome::Failed(err.clone());
                }
                results
            }
        }
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        self.producer.flush().map_err(|e| anyhow::anyhow!(e))
    }
}

/// The prep → publish → fold dance for the outputs layer. No
/// `capture_event_batch_size` here: the outputs facade records it for
/// every backend uniformly, where the retiring `Event` impls record it
/// themselves.
#[async_trait]
impl<P: KafkaProducer + 'static> Prepare for KafkaSinkBase<P> {
    async fn publish_one(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.kafka_send(event)?
            .instrument(info_span!("ack_wait_one"))
            .await
    }

    async fn publish_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let payloads = self.prepare_batch(events).await?;
        fold_results(self.publish(payloads).await)
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        Sink::flush(self)
    }
}

#[async_trait]
impl<P: KafkaProducer + 'static> Event for KafkaSinkBase<P> {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let ack_future = self.kafka_send(event)?;
        histogram!("capture_event_batch_size").record(1.0);
        ack_future.instrument(info_span!("ack_wait_one")).await
    }

    /// The v0 bridge onto the mechanism seam: prep, publish, fold. The
    /// per-event results collapse to the whole-request `CaptureError` the
    /// `Event` callers expect.
    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        // Record the batch-size histogram up front so the distribution is a
        // faithful view of batches submitted, not only those that succeeded.
        // Matches the single-event `send` path which records before any await.
        histogram!("capture_event_batch_size").record(events.len() as f64);

        Prepare::publish_batch(self, events).await
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        Sink::flush(self)
    }
}

/// Concurrent ack drain for `Sink::publish`, fail-fast on first ack error.
/// Dropping the JoinSet on error aborts remaining spawned ack futures;
/// DeliveryAckFuture Drop then records the "dropped" outcome on
/// capture_kafka_produce_ack_duration_ms.
async fn drain_acks(mut ack_set: JoinSet<Result<(), CaptureError>>) -> Result<(), CaptureError> {
    async move {
        while let Some(res) = ack_set.join_next().await {
            match res {
                Ok(Ok(_)) => {}
                Ok(Err(err)) => {
                    ack_set.abort_all();
                    return Err(err);
                }
                Err(err) => {
                    ack_set.abort_all();
                    error!("join error while waiting on Kafka ACK: {err:#}");
                    return Err(CaptureError::RetryableSinkError);
                }
            }
        }
        Ok(())
    }
    .instrument(info_span!("ack_wait_many"))
    .await
}

#[cfg(test)]
pub(crate) use crate::sinks::registry::test_topics;

#[cfg(test)]
mod tests {
    use crate::api::CaptureError;
    use crate::config::{self, EnvelopeCompression};
    use crate::sinks::kafka::KafkaSink;
    use crate::sinks::Event;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, OverflowReason, ProcessedEvent, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use rand::distributions::Alphanumeric;
    use rand::Rng;
    use rdkafka::mocking::MockCluster;
    use rdkafka::producer::DefaultProducerContext;
    use rdkafka::types::{RDKafkaApiKey, RDKafkaRespErr};
    use tokio_util::sync::CancellationToken;

    async fn start_on_mocked_sink(
        message_max_bytes: Option<u32>,
    ) -> (MockCluster<'static, DefaultProducerContext>, KafkaSink) {
        let shutdown_token = CancellationToken::new();
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_shutdown_token(shutdown_token)
            .build();
        let handle = manager.register(
            "sink",
            lifecycle::ComponentOptions::new()
                .with_liveness_deadline(std::time::Duration::from_secs(30)),
        );
        let _monitor = manager.monitor_background();
        let cluster = MockCluster::new(1).expect("failed to create mock brokers");
        let config = config::KafkaConfig {
            kafka_producer_linger_ms: 0,
            kafka_producer_queue_mib: 50,
            kafka_message_timeout_ms: 500,
            kafka_topic_metadata_refresh_interval_ms: 20000,
            kafka_producer_message_max_bytes: message_max_bytes.unwrap_or(1000000),
            kafka_compression_codec: "none".to_string(),
            kafka_hosts: cluster.bootstrap_servers(),
            kafka_topic: "events_plugin_ingestion".to_string(),
            kafka_overflow_topic: "events_plugin_ingestion_overflow".to_string(),
            kafka_historical_topic: "events_plugin_ingestion_historical".to_string(),
            kafka_client_ingestion_warning_topic: "events_plugin_ingestion".to_string(),
            kafka_error_tracking_topic: "error_tracking_events".to_string(),
            kafka_heatmaps_topic: "events_plugin_ingestion".to_string(),
            kafka_replay_overflow_topic: "session_recording_snapshot_item_overflow".to_string(),
            kafka_dlq_topic: "events_plugin_ingestion_dlq".to_string(),
            outputs_completeness_check_enabled: true,
            capture_analytics_ai_events_topic: "events_plugin_ingestion_ai".to_string(),
            capture_analytics_ai_events_overflow_topic: None,
            kafka_traces_topic: "traces_ingestion".to_string(),
            kafka_metrics_topic: "metrics_ingestion".to_string(),
            kafka_tls: false,
            kafka_client_id: "".to_string(),
            kafka_metadata_max_age_ms: 60000,
            kafka_producer_max_retries: 2,
            kafka_producer_acks: "all".to_string(),
            kafka_socket_timeout_ms: 60000,
            kafka_producer_batch_num_messages: 10000,
            kafka_producer_batch_size: 1000000,
            kafka_producer_max_in_flight_requests: 1000000,
            kafka_producer_sticky_partitioning_linger_ms: 10,
            kafka_producer_enable_idempotence: false,
            kafka_producer_partitioner: "murmur2_random".to_string(),
            kafka_broker_address_family: String::new(),
            kafka_log_connection_close: true,
            kafka_producer_queue_buffering_max_messages: 100000,
            kafka_retry_backoff_max_ms: 1000,
            kafka_socket_send_buffer_bytes: 0,
            kafka_socket_receive_buffer_bytes: 0,
            kafka_traces_hosts: None,
            kafka_traces_tls: None,
            kafka_traces_client_id: None,
            kafka_traces_compression_codec: None,
            kafka_traces_producer_acks: None,
            kafka_traces_producer_linger_ms: None,
            kafka_traces_producer_queue_mib: None,
            kafka_traces_message_timeout_ms: None,
            kafka_traces_producer_message_max_bytes: None,
            kafka_traces_producer_max_retries: None,
            kafka_traces_topic_metadata_refresh_interval_ms: None,
            kafka_traces_metadata_max_age_ms: None,
            kafka_metrics_hosts: None,
            kafka_metrics_tls: None,
            kafka_metrics_client_id: None,
            kafka_metrics_compression_codec: None,
            kafka_metrics_producer_acks: None,
            kafka_metrics_producer_linger_ms: None,
            kafka_metrics_producer_queue_mib: None,
            kafka_metrics_message_timeout_ms: None,
            kafka_metrics_producer_message_max_bytes: None,
            kafka_metrics_producer_max_retries: None,
            kafka_metrics_topic_metadata_refresh_interval_ms: None,
            kafka_metrics_metadata_max_age_ms: None,
            kafka_replay_envelope_compression: EnvelopeCompression::None,
        };
        let sink = KafkaSink::new(config, Some(handle))
            .await
            .expect("failed to create sink");
        (cluster, sink)
    }

    #[tokio::test]
    async fn kafka_sink_error_handling() {
        // Uses a mocked Kafka broker that allows injecting write errors, to check error handling.
        // We test different cases in a single test to amortize the startup cost of the producer.

        let (cluster, sink) = start_on_mocked_sink(Some(3000000)).await;
        let distinct_id = "test_distinct_id_123".to_string();
        let timestamp = chrono::Utc::now();
        let event: CapturedEvent = CapturedEvent {
            uuid: uuid_v7_from_datetime(timestamp),
            distinct_id: distinct_id.clone(),
            session_id: None,
            ip: "".to_string(),
            data: "".to_string(),
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            event: "test_event".to_string(),
            timestamp,
            is_cookieless_mode: false,
            historical_migration: false,
        };

        let metadata = ProcessedEventMetadata {
            data_type: DataType::AnalyticsMain,
            session_id: None,
            computed_timestamp: None,
            event_name: "test_event".to_string(),
            force_overflow: false,
            skip_person_processing: false,
            redirect_to_dlq: false,
            redirect_to_topic: None,
            skip_heatmap_processing: false,
            overflow_reason: None,
            distinct_id_truncated_from: None,
        };

        let event = ProcessedEvent {
            event,
            metadata: metadata.clone(),
        };

        // Wait for producer to be healthy, to keep kafka_message_timeout_ms short and tests faster
        for _ in 0..20 {
            if sink.send(event.clone()).await.is_ok() {
                break;
            }
        }

        // Send events to confirm happy path
        sink.send(event.clone())
            .await
            .expect("failed to send one initial event");
        sink.send_batch(vec![event.clone(), event.clone()])
            .await
            .expect("failed to send initial event batch");

        // Producer should accept a 2MB message as we set message.max.bytes to 3MB
        let big_data = rand::thread_rng()
            .sample_iter(Alphanumeric)
            .take(2_000_000)
            .map(char::from)
            .collect();
        let timestamp = chrono::Utc::now();
        let captured = CapturedEvent {
            uuid: uuid_v7_from_datetime(timestamp),
            distinct_id: "id1".to_string(),
            session_id: None,
            ip: "".to_string(),
            data: big_data,
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            event: "test_event".to_string(),
            timestamp,
            is_cookieless_mode: false,
            historical_migration: false,
        };

        let big_event = ProcessedEvent {
            event: captured,
            metadata: metadata.clone(),
        };

        sink.send(big_event)
            .await
            .expect("failed to send event larger than default max size");

        // Producer should reject a 4MB message
        let big_data = rand::thread_rng()
            .sample_iter(Alphanumeric)
            .take(4_000_000)
            .map(char::from)
            .collect();

        let timestamp = chrono::Utc::now();
        let big_event = ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7_from_datetime(timestamp),
                distinct_id: "id1".to_string(),
                session_id: None,
                ip: "".to_string(),
                data: big_data,
                now: "".to_string(),
                sent_at: None,
                token: "token1".to_string(),
                event: "test_event".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            },
            metadata: metadata.clone(),
        };

        match sink.send(big_event).await {
            Err(CaptureError::EventTooBig(_)) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };

        // Simulate unretriable errors
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_MSG_SIZE_TOO_LARGE; 1];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send(event.clone()).await {
            Err(CaptureError::EventTooBig(_)) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_INVALID_PARTITIONS; 1];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send_batch(vec![event.clone(), event.clone()]).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };

        // Simulate transient errors, messages should go through OK
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 2];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        sink.send(event.clone())
            .await
            .expect("failed to send one event after recovery");
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 2];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        sink.send_batch(vec![event.clone(), event.clone()])
            .await
            .expect("failed to send event batch after recovery");

        // Timeout on a sustained transient error
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 50];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send(event.clone()).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };
        match sink.send_batch(vec![event.clone(), event.clone()]).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {err}"),
            Ok(()) => panic!("should have errored"),
        };
    }

    #[tokio::test]
    async fn test_historical_migration_headers() {
        use common_types::CapturedEventHeaders;
        use rdkafka::message::OwnedHeaders;

        // Test that historical_migration=true is set in headers for AnalyticsHistorical
        let headers_historical = CapturedEventHeaders {
            token: Some("test_token".to_string()),
            distinct_id: Some("test_id".to_string()),
            session_id: None,
            timestamp: Some("2023-01-01T12:00:00Z".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("test-uuid".to_string()),
            now: Some("2023-01-01T12:00:00Z".to_string()),
            force_disable_person_processing: None,
            historical_migration: Some(true),
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        };

        let owned_headers: OwnedHeaders = headers_historical.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);
        assert_eq!(parsed_headers.historical_migration, Some(true));
        assert_eq!(parsed_headers.now, Some("2023-01-01T12:00:00Z".to_string()));

        let headers_main = CapturedEventHeaders {
            token: Some("test_token".to_string()),
            distinct_id: Some("test_id".to_string()),
            session_id: None,
            timestamp: Some("2023-01-01T12:00:00Z".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("test-uuid".to_string()),
            now: Some("2023-01-01T12:00:00Z".to_string()),
            force_disable_person_processing: None,
            historical_migration: Some(false),
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        };

        let owned_headers: OwnedHeaders = headers_main.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);
        assert_eq!(parsed_headers.historical_migration, Some(false));
        assert_eq!(parsed_headers.now, Some("2023-01-01T12:00:00Z".to_string()));
    }

    #[tokio::test]
    async fn test_now_header_is_set() {
        use common_types::CapturedEventHeaders;
        use rdkafka::message::OwnedHeaders;

        // Test that the 'now' header is correctly set and parsed
        let test_now = "2024-01-15T10:30:45Z".to_string();
        let headers = CapturedEventHeaders {
            token: Some("test_token".to_string()),
            distinct_id: Some("test_id".to_string()),
            session_id: None,
            timestamp: Some("2024-01-15T10:30:00Z".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("test-uuid".to_string()),
            now: Some(test_now.clone()),
            force_disable_person_processing: None,
            historical_migration: None,
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        };

        // Convert to owned headers and back
        let owned_headers: OwnedHeaders = headers.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);

        // Verify the 'now' field is preserved
        assert_eq!(parsed_headers.now, Some(test_now));
        assert_eq!(parsed_headers.token, Some("test_token".to_string()));
        assert_eq!(parsed_headers.distinct_id, Some("test_id".to_string()));
    }

    #[tokio::test]
    async fn test_dlq_headers_are_set() {
        use common_types::CapturedEventHeaders;
        use rdkafka::message::OwnedHeaders;

        // Test that the 'now' header is correctly set and parsed
        let test_now = "2024-01-15T10:30:45Z".to_string();
        let dlq_timestamp = "2025-01-15T10:30:45Z".to_string();
        let headers = CapturedEventHeaders {
            token: Some("test_token".to_string()),
            distinct_id: Some("test_id".to_string()),
            session_id: None,
            timestamp: Some("2024-01-15T10:30:00Z".to_string()),
            event: Some("test_event".to_string()),
            uuid: Some("test-uuid".to_string()),
            now: Some(test_now.clone()),
            force_disable_person_processing: None,
            historical_migration: None,
            skip_heatmap_processing: None,
            dlq_reason: Some("test reason".to_string()),
            dlq_step: Some("test step".to_string()),
            dlq_timestamp: Some(dlq_timestamp.clone()),
            content_encoding: None,
        };

        // Convert to owned headers and back
        let owned_headers: OwnedHeaders = headers.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);

        // Verify the 'now' field is preserved
        assert_eq!(parsed_headers.dlq_reason, Some("test reason".to_string()));
        assert_eq!(parsed_headers.dlq_step, Some("test step".to_string()));
        assert_eq!(parsed_headers.dlq_timestamp, Some(dlq_timestamp));
    }

    #[cfg(test)]
    mod topic_routing {
        use super::*;
        use crate::sinks::kafka::{test_topics, KafkaSinkBase, SCATTER_GATHER_MIN_BATCH};
        use crate::sinks::producer::MockKafkaProducer;
        use crate::sinks::sink::{Outcome, Sink};
        use rstest::rstest;

        const MAIN_TOPIC: &str = "events_plugin_ingestion";
        const OVERFLOW_TOPIC: &str = "events_plugin_ingestion_overflow";
        const DLQ_TOPIC: &str = "events_plugin_ingestion_dlq";
        const HISTORICAL_TOPIC: &str = "events_plugin_ingestion_historical";
        const HEATMAPS_TOPIC: &str = "heatmaps";
        const CLIENT_INGESTION_WARNING_TOPIC: &str = "client_ingestion_warning";
        const REPLAY_OVERFLOW_TOPIC: &str = "replay_overflow";
        const ERROR_TRACKING_TOPIC: &str = "error_tracking_events";
        const AI_EVENTS_TOPIC: &str = "ai_events";
        const AI_EVENTS_OVERFLOW_TOPIC: &str = "ai_events_overflow";

        /// Which reroute counter (if any) an event must increment. DLQ and
        /// custom-topic redirects are mutually exclusive at the sink because DLQ
        /// takes strict priority, so a single event fires at most one counter.
        #[derive(Clone, Copy, PartialEq, Debug)]
        enum Rerouted {
            None,
            Dlq,
            CustomTopic,
        }

        struct EventInput {
            data_type: DataType,
            force_overflow: bool,
            skip_person_processing: bool,
            skip_heatmap_processing: bool,
            redirect_to_dlq: bool,
            redirect_to_topic: Option<String>,
            overflow_reason: Option<OverflowReason>,
            compression: EnvelopeCompression,
        }

        impl Default for EventInput {
            fn default() -> Self {
                Self {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    skip_heatmap_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    compression: EnvelopeCompression::None,
                }
            }
        }

        fn create_test_event(input: &EventInput) -> ProcessedEvent {
            let timestamp = chrono::Utc::now();
            let event = CapturedEvent {
                uuid: uuid_v7_from_datetime(timestamp),
                distinct_id: "test_user".to_string(),
                session_id: Some("session123".to_string()),
                ip: "127.0.0.1".to_string(),
                data: "{}".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                event: "test_event".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            };

            let metadata = ProcessedEventMetadata {
                data_type: input.data_type,
                session_id: Some("session123".to_string()),
                computed_timestamp: None,
                event_name: "test_event".to_string(),
                force_overflow: input.force_overflow,
                skip_person_processing: input.skip_person_processing,
                redirect_to_dlq: input.redirect_to_dlq,
                redirect_to_topic: input.redirect_to_topic.clone(),
                skip_heatmap_processing: input.skip_heatmap_processing,
                overflow_reason: input.overflow_reason.clone(),
                distinct_id_truncated_from: None,
            };

            ProcessedEvent { event, metadata }
        }

        /// The full routing fingerprint of one event: topic + partition key +
        /// every header the sink can stamp + which reroute counter (if any)
        /// fires. This is the golden oracle produce-path refactors prove wire
        /// parity against, so each field is stated explicitly rather than
        /// re-derived from the input. Fields default to the "normal main-topic" outcome so
        /// each case only spells out what makes it different.
        struct ExpectedRouting<'a> {
            topic: &'a str,
            has_key: bool,
            force_disable_person_processing: Option<bool>,
            skip_heatmap_processing: Option<bool>,
            content_encoding: Option<&'a str>,
            dlq_headers: bool,
            rerouted: Rerouted,
        }

        impl Default for ExpectedRouting<'_> {
            fn default() -> Self {
                Self {
                    topic: "",
                    has_key: true,
                    force_disable_person_processing: None,
                    skip_heatmap_processing: None,
                    content_encoding: None,
                    dlq_headers: false,
                    rerouted: Rerouted::None,
                }
            }
        }

        async fn assert_routing(input: EventInput, expected: ExpectedRouting<'_>) {
            // Capture reroute counters on a thread-local recorder. `assert_routing`
            // runs on the default current-thread test runtime and `send` prepares
            // the record inline before the first await, so the guard stays visible
            // when `prepare_record` increments the counter.
            let recorder = metrics_util::debugging::DebuggingRecorder::new();
            let snapshotter = recorder.snapshotter();
            let _guard = metrics::set_default_local_recorder(&recorder);

            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer_and_compression(
                producer.clone(),
                test_topics(),
                input.compression,
            );

            let event = create_test_event(&input);
            sink.send(event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1, "Expected exactly one record");
            let record = &records[0];
            let headers = &record.headers;

            let ctx = format!(
                "{:?} (force_overflow={}, skip_person={}, skip_heatmap={}, dlq={}, redirect_to_topic={:?}, overflow_reason={:?})",
                input.data_type,
                input.force_overflow,
                input.skip_person_processing,
                input.skip_heatmap_processing,
                input.redirect_to_dlq,
                input.redirect_to_topic,
                input.overflow_reason,
            );

            assert_eq!(record.topic, expected.topic, "wrong topic for {ctx}");
            assert_eq!(
                record.key.is_some(),
                expected.has_key,
                "wrong key presence for {ctx}"
            );
            assert_eq!(
                headers.force_disable_person_processing, expected.force_disable_person_processing,
                "wrong force_disable_person_processing header for {ctx}"
            );
            assert_eq!(
                headers.skip_heatmap_processing, expected.skip_heatmap_processing,
                "wrong skip_heatmap_processing header for {ctx}"
            );
            assert_eq!(
                headers.content_encoding.as_deref(),
                expected.content_encoding,
                "wrong content_encoding header for {ctx}"
            );

            // DLQ headers travel as a set: a reason, a step, and a valid RFC-3339
            // timestamp when the event is routed to the DLQ; all three absent on
            // every other route.
            if expected.dlq_headers {
                assert_eq!(
                    headers.dlq_reason.as_deref(),
                    Some("event_restriction"),
                    "wrong dlq_reason for {ctx}"
                );
                assert_eq!(
                    headers.dlq_step.as_deref(),
                    Some("capture"),
                    "wrong dlq_step for {ctx}"
                );
                let ts = headers
                    .dlq_timestamp
                    .as_deref()
                    .unwrap_or_else(|| panic!("dlq_timestamp missing for {ctx}"));
                chrono::DateTime::parse_from_rfc3339(ts).unwrap_or_else(|e| {
                    panic!("dlq_timestamp '{ts}' is not valid RFC 3339 for {ctx}: {e}")
                });
            } else {
                assert_eq!(
                    headers.dlq_reason, None,
                    "dlq_reason must be absent for {ctx}"
                );
                assert_eq!(headers.dlq_step, None, "dlq_step must be absent for {ctx}");
                assert_eq!(
                    headers.dlq_timestamp, None,
                    "dlq_timestamp must be absent for {ctx}"
                );
            }

            // Exactly one reroute counter fires per redirected event; neither
            // fires on the normal per-datatype or overflow paths.
            let snapshot = snapshotter.snapshot().into_vec();
            let count = |name: &str| -> Option<u64> {
                snapshot.iter().find_map(|(key, _, _, value)| {
                    if key.key().name() != name {
                        return None;
                    }
                    match value {
                        metrics_util::debugging::DebugValue::Counter(v) => Some(*v),
                        _ => None,
                    }
                })
            };
            // Recorder liveness: enqueue emits the bytes counter for every
            // record, on the same inline pre-await path as the reroute
            // counters. If it is absent, the thread-local recorder is no
            // longer observing prep (e.g. prep moved to a spawned thread)
            // and every absence assertion below would pass vacuously — so
            // fail here first, in every case.
            assert_eq!(
                count("capture_kafka_produce_bytes_total"),
                Some(record.payload.len() as u64),
                "recorder did not observe the produce path for {ctx}; \
                 the counter assertions below cannot be trusted"
            );

            let dlq_count = count("capture_events_rerouted_dlq");
            let custom_count = count("capture_events_rerouted_custom_topic");
            match expected.rerouted {
                Rerouted::None => {
                    assert_eq!(
                        dlq_count, None,
                        "capture_events_rerouted_dlq must not fire for {ctx}"
                    );
                    assert_eq!(
                        custom_count, None,
                        "capture_events_rerouted_custom_topic must not fire for {ctx}"
                    );
                }
                Rerouted::Dlq => {
                    assert_eq!(
                        dlq_count,
                        Some(1),
                        "capture_events_rerouted_dlq must fire once for {ctx}"
                    );
                    assert_eq!(
                        custom_count, None,
                        "capture_events_rerouted_custom_topic must not fire for {ctx}"
                    );
                }
                Rerouted::CustomTopic => {
                    assert_eq!(
                        custom_count,
                        Some(1),
                        "capture_events_rerouted_custom_topic must fire once for {ctx}"
                    );
                    assert_eq!(
                        dlq_count, None,
                        "capture_events_rerouted_dlq must not fire for {ctx}"
                    );
                }
            }
        }

        // ==================== AnalyticsMain ====================

        #[tokio::test]
        async fn analytics_main_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_force_overflow_with_skip_person() {
            // Key should be dropped when both force_overflow and skip_person_processing are set
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_skip_person_only() {
            // Key should be dropped when skip_person_processing is set, even without overflow
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_dlq_priority_over_overflow() {
            // DLQ takes priority over force_overflow
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_dlq_with_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_all_flags() {
            // DLQ takes priority, skip_person still sets header
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    skip_person_processing: true,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== AnalyticsHistorical ====================
        // Historical events IGNORE force_overflow - they never overflow

        #[tokio::test]
        async fn analytics_historical_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_historical_ignores_force_overflow() {
            // Historical events should ignore force_overflow
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_historical_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_historical_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_historical_all_flags() {
            // DLQ takes priority, historical ignores overflow, skip_person sets header
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    force_overflow: true,
                    skip_person_processing: true,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== SnapshotMain ====================

        #[tokio::test]
        async fn snapshot_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: REPLAY_OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_force_overflow_with_skip_person() {
            // Unlike AnalyticsMain, SnapshotMain does NOT drop key with skip_person_processing
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: true,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: REPLAY_OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_skip_person_only() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_dlq_priority_over_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_lz4_sets_content_encoding_header() {
            // With envelope compression on, a snapshot event carries the
            // `content-encoding: lz4` header alongside its normal main-topic
            // routing. The compressed-payload bytes are covered by the lz4
            // payload goldens below; here the oracle pins just the header.
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    compression: EnvelopeCompression::Lz4,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    content_encoding: Some("lz4"),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_lz4_leaves_content_encoding_unset() {
            // Envelope compression only applies to snapshots: a non-snapshot
            // event under the same sink config carries no content-encoding.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    compression: EnvelopeCompression::Lz4,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== HeatmapMain ====================
        // Heatmaps IGNORE force_overflow

        #[tokio::test]
        async fn heatmap_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn heatmap_ignores_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn heatmap_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn heatmap_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn heatmap_skip_heatmap_processing_sets_header() {
            // The skip_heatmap_processing metadata flag stamps its own header,
            // independent of the routing topic and the person-processing flag.
            assert_routing(
                EventInput {
                    data_type: DataType::HeatmapMain,
                    skip_heatmap_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    skip_heatmap_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_skip_heatmap_processing_sets_header() {
            // skip_heatmap_processing is not gated on data type: it rides through
            // for AnalyticsMain too, orthogonally to skip_person_processing.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    skip_heatmap_processing: true,
                    skip_person_processing: true,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    skip_heatmap_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== ExceptionErrorTracking ====================
        // Exceptions IGNORE force_overflow

        #[tokio::test]
        async fn exception_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_ignores_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== ClientIngestionWarning ====================
        // ClientIngestionWarning IGNORES force_overflow

        #[tokio::test]
        async fn client_ingestion_warning_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn client_ingestion_warning_ignores_force_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn client_ingestion_warning_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn client_ingestion_warning_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== AiEvents ====================
        // The dedicated $ai_* lane routes to its own topic, keyed on the
        // event key. test_topics() arms the AI overflow valve
        // (CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC), so overflow handling mirrors the
        // AnalyticsMain arm onto the AI topics; the unarmed tests below
        // override the valve off.

        #[tokio::test]
        async fn ai_events_normal() {
            assert_routing(
                EventInput {
                    data_type: DataType::AiEvents,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: AI_EVENTS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn ai_events_force_overflow_reroutes_when_armed() {
            // With the valve armed, restriction-driven force_overflow behaves
            // exactly like the analytics main lane: rerouted, key kept.
            assert_routing(
                EventInput {
                    data_type: DataType::AiEvents,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: AI_EVENTS_OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn ai_events_force_overflow_with_skip_person_drops_key() {
            // Mirrors analytics_main_force_overflow_with_skip_person.
            assert_routing(
                EventInput {
                    data_type: DataType::AiEvents,
                    force_overflow: true,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: AI_EVENTS_OVERFLOW_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        /// Stamped overflow reasons on the AI lane, where — unlike the
        /// analytics lane — a burst without locality preservation spreads
        /// while person processing is on: the AI consumer reads persons
        /// without writing them, so keyless person-on records contend
        /// nothing downstream. `ForceLimited` implies the person-processing
        /// header on its own, flag or no flag.
        #[rstest]
        #[case::force_limited(OverflowReason::ForceLimited, false, Some(true))]
        #[case::rate_limited_preserving(
            OverflowReason::RateLimited {
                preserve_locality: true
            },
            true,
            None
        )]
        #[case::rate_limited_spreading(
            OverflowReason::RateLimited {
                preserve_locality: false
            },
            false,
            None
        )]
        #[tokio::test]
        async fn ai_events_stamped_overflow_routing(
            #[case] reason: OverflowReason,
            #[case] has_key: bool,
            #[case] force_disable_person_processing: Option<bool>,
        ) {
            assert_routing(
                EventInput {
                    data_type: DataType::AiEvents,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: Some(reason),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: AI_EVENTS_OVERFLOW_TOPIC,
                    has_key,
                    force_disable_person_processing,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn ai_events_unarmed_never_overflows() {
            // Without CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC the lane keeps today's
            // behavior: force_overflow and any stamped reason (which the
            // gated pipeline would not produce anyway) are ignored.
            let producer = MockKafkaProducer::new();
            let mut topics = test_topics();
            topics.ai_events_overflow = None;
            let sink = KafkaSinkBase::with_producer(producer.clone(), topics);

            let mut event = create_test_event(&EventInput {
                data_type: DataType::AiEvents,
                force_overflow: true,
                skip_person_processing: false,
                redirect_to_dlq: false,
                redirect_to_topic: None,
                overflow_reason: None,
                ..Default::default()
            });
            event.metadata.overflow_reason = Some(OverflowReason::ForceLimited);
            sink.send(event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1);
            assert_eq!(records[0].topic, AI_EVENTS_TOPIC);
            assert_eq!(records[0].key.as_deref(), Some("test_token:test_user"));
        }

        #[tokio::test]
        async fn ai_events_skip_person_keeps_key() {
            // skip_person_processing sets the header but must not null the
            // key: v1's sink only nulls keys for Main/Overflow destinations.
            assert_routing(
                EventInput {
                    data_type: DataType::AiEvents,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: AI_EVENTS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn ai_events_redirect_to_dlq() {
            assert_routing(
                EventInput {
                    data_type: DataType::AiEvents,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: None,
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn ai_events_redirect_to_topic_wins() {
            // A restriction-driven redirect beats the AI lane, matching v1
            // where Destination::Custom overwrites Destination::AiEvents.
            assert_routing(
                EventInput {
                    data_type: DataType::AiEvents,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: None,
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn ai_events_record_matches_other_lanes_byte_for_byte() {
            // The AI lane must only change the topic: for the same event, the
            // record key is the event key (token:distinct_id) and the headers
            // are identical to what another dedicated lane produces.
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let base = create_test_event(&EventInput::default());
            let mut ai_event = base.clone();
            ai_event.metadata.data_type = DataType::AiEvents;
            let mut exception_event = base;
            exception_event.metadata.data_type = DataType::ExceptionErrorTracking;

            sink.send(ai_event).await.unwrap();
            sink.send(exception_event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 2);
            assert_eq!(records[0].topic, AI_EVENTS_TOPIC);
            assert_eq!(records[1].topic, ERROR_TRACKING_TOPIC);
            assert_eq!(records[0].key.as_deref(), Some("test_token:test_user"));
            assert_eq!(records[0].key, records[1].key);
            assert_eq!(records[0].payload, records[1].payload);
            assert_eq!(
                format!("{:?}", records[0].headers),
                format!("{:?}", records[1].headers)
            );
        }

        // ==================== RedirectToTopic ====================
        // redirect_to_topic overrides normal routing but DLQ takes priority

        #[tokio::test]
        async fn analytics_main_redirect_to_topic() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: None,
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_dlq_priority_over_redirect_to_topic() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: true,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_redirect_to_topic_priority_over_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: None,
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_redirect_to_topic_with_skip_person() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: true,
                    redirect_to_dlq: false,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn snapshot_redirect_to_topic() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    overflow_reason: None,
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: None,
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== overflow_reason routing tests ====================
        // The pipeline stamps ProcessedEventMetadata::overflow_reason upstream;
        // the sink is a pure mechanism layer that switches on it. These cover
        // each variant: ForceLimited, RateLimited { preserve_locality }, and
        // ReplayLimited. `force_overflow` coexistence is covered by the
        // analytics_main_force_overflow / snapshot_main_force_overflow cases
        // above (force_overflow short-circuits the overflow_reason branch).

        /// `ForceLimited` implies person processing is off on its own: the
        /// header is set whether or not the stamping site also set the flag,
        /// so a keyless force-limited record can never reach person
        /// processing with identity resolution still on.
        #[rstest]
        #[case::stamped_with_flag(true)]
        #[case::reason_only(false)]
        #[tokio::test]
        async fn overflow_reason_force_limited_routes_to_overflow_with_null_key(
            #[case] skip_person_processing: bool,
        ) {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    skip_person_processing,
                    overflow_reason: Some(OverflowReason::ForceLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        /// A person-on burst keeps its key on the analytics lane regardless of
        /// the locality preference: the overflow consumer updates persons
        /// keyed on distinct id, and spreading one distinct id across
        /// partitions contends those updates.
        #[rstest]
        #[case::preserving_locality(true)]
        #[case::spreading(false)]
        #[tokio::test]
        async fn overflow_reason_rate_limited_keeps_key_while_person_processing_on(
            #[case] preserve_locality: bool,
        ) {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    overflow_reason: Some(OverflowReason::RateLimited { preserve_locality }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        /// The wire outcome for the combination the global rate limiter and the
        /// overflow limiter produce together (the GRL stamps the person flag,
        /// the burst limiter overwrites the reason): the record keeps the
        /// person-processing header and loses the partition key, on either
        /// locality setting.
        #[rstest]
        #[case::analytics_preserving(DataType::AnalyticsMain, true, OVERFLOW_TOPIC)]
        #[case::analytics_spreading(DataType::AnalyticsMain, false, OVERFLOW_TOPIC)]
        #[case::ai_preserving(DataType::AiEvents, true, AI_EVENTS_OVERFLOW_TOPIC)]
        #[tokio::test]
        async fn overflow_reason_rate_limited_drops_key_when_person_off(
            #[case] data_type: DataType,
            #[case] preserve_locality: bool,
            #[case] expected_topic: &str,
        ) {
            assert_routing(
                EventInput {
                    data_type,
                    skip_person_processing: true,
                    overflow_reason: Some(OverflowReason::RateLimited { preserve_locality }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: expected_topic,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_ignored_for_analytics_historical() {
            // historical events never go through overflow routing even if the
            // upstream pipeline accidentally stamps one — be defensive.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsHistorical,
                    overflow_reason: Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_replay_limited_routes_snapshot_to_replay_overflow() {
            assert_routing(
                EventInput {
                    data_type: DataType::SnapshotMain,
                    overflow_reason: Some(OverflowReason::ReplayLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: REPLAY_OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_force_overflow_short_circuits_overflow_reason() {
            // Precedence check: force_overflow set by event restrictions wins
            // over any overflow_reason stamped by the governor. This ensures
            // the event_restriction counter label stays distinct from
            // force_limited / rate_limited labels.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    overflow_reason: Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_redirect_to_dlq_wins_over_overflow_reason() {
            // DLQ routing is the highest-priority routing decision: it wins
            // over both force_overflow and overflow_reason. The
            // person-processing header still travels with the ForceLimited
            // reason — routing precedence changes the topic, not the skip
            // (production stamps the flag alongside the reason anyway).
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    redirect_to_dlq: true,
                    overflow_reason: Some(OverflowReason::ForceLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                    dlq_headers: true,
                    rerouted: Rerouted::Dlq,
                    ..Default::default()
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_redirect_to_topic_wins_over_overflow_reason() {
            // Custom topic redirect (set by event restrictions) also wins over
            // overflow_reason since overflow decisions cannot compose with a
            // hard-coded topic override.
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    redirect_to_topic: Some("custom_topic".to_string()),
                    overflow_reason: Some(OverflowReason::ForceLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    // The header travels with the reason regardless of the
                    // routing precedence, as in the dlq case above.
                    force_disable_person_processing: Some(true),
                    rerouted: Rerouted::CustomTopic,
                    ..Default::default()
                },
            )
            .await;
        }

        // ==================== send_batch ordering + error tests ====================
        // These exercise the B2 three-phase send_batch: parallel prepare_record,
        // serial enqueue_record, concurrent ack drain. The ordering test runs on
        // a multi-thread runtime so phase 1 actually parallelizes across workers
        // and we can detect if phase 2 is accidentally reordering records.

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_preserves_order_same_key() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            // 20 events, all sharing the same distinct_id (so they hash to the
            // same partition via murmur2), each with a unique UUID so we can
            // track input->output order through the pipeline.
            let events: Vec<ProcessedEvent> = (0..20)
                .map(|_| {
                    create_test_event(&EventInput {
                        data_type: DataType::AnalyticsMain,
                        force_overflow: false,
                        skip_person_processing: false,
                        redirect_to_dlq: false,
                        redirect_to_topic: None,
                        overflow_reason: None,
                        ..Default::default()
                    })
                })
                .collect();

            let input_uuids: Vec<String> =
                events.iter().map(|e| e.event.uuid.to_string()).collect();

            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), 20, "expected 20 records");

            // Parse the UUID out of each record's serialized payload and compare
            // against the input order. If phase 2 ever reorders enqueue calls,
            // librdkafka's partition-order guarantee would be broken for same-key
            // events and this assertion trips.
            let output_uuids: Vec<String> = records
                .iter()
                .map(|r| {
                    let v: serde_json::Value =
                        serde_json::from_slice(&r.payload).expect("payload is valid json");
                    v.get("uuid")
                        .and_then(|u| u.as_str())
                        .expect("uuid field present")
                        .to_string()
                })
                .collect();

            assert_eq!(
                output_uuids, input_uuids,
                "send_batch must preserve input order for same-key events"
            );

            // Sanity: all records share the same partition key.
            let first_key = records[0].key.as_deref().expect("partition key set");
            for r in &records {
                assert_eq!(
                    r.key.as_deref(),
                    Some(first_key),
                    "all events should share partition key"
                );
            }
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_prep_error_aborts_batch() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            // Build a batch where event #3 is a SnapshotMain with session_id=None,
            // which causes prepare_record to return MissingSessionId. The other
            // events are valid AnalyticsMain. Since phase 2 only runs after all
            // prep tasks complete, a prep error must short-circuit before any
            // producer.send() call — so the mock producer should see zero records.
            let mut events: Vec<ProcessedEvent> = (0..5)
                .map(|_| {
                    create_test_event(&EventInput {
                        data_type: DataType::AnalyticsMain,
                        force_overflow: false,
                        skip_person_processing: false,
                        redirect_to_dlq: false,
                        redirect_to_topic: None,
                        overflow_reason: None,
                        ..Default::default()
                    })
                })
                .collect();

            // Overwrite element [2] with a SnapshotMain event whose session_id
            // metadata is None — prepare_record returns MissingSessionId at the
            // session_id lookup in the SnapshotMain branch.
            let mut bad = create_test_event(&EventInput {
                data_type: DataType::SnapshotMain,
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: false,
                redirect_to_topic: None,
                overflow_reason: None,
                ..Default::default()
            });
            bad.metadata.session_id = None;
            events[2] = bad;

            let res = sink.send_batch(events).await;
            match res {
                Err(CaptureError::MissingSessionId) => {}
                Err(other) => panic!("expected MissingSessionId, got {other:?}"),
                Ok(()) => panic!("expected send_batch to fail on prep error"),
            }

            let records = producer.get_records();
            assert!(
                records.is_empty(),
                "no records should reach the producer when prep phase fails; got {} records",
                records.len()
            );
        }

        // ==================== send_batch fast-path + mid-batch failure tests ====================

        /// Builds N AnalyticsMain events with sequential distinct_ids so each
        /// record is individually identifiable in the mock producer's output.
        fn build_batch(n: usize) -> Vec<ProcessedEvent> {
            (0..n)
                .map(|i| {
                    let mut e = create_test_event(&EventInput::default());
                    e.event.distinct_id = format!("user_{i}");
                    e
                })
                .collect()
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_mid_enqueue_failure_preserves_earlier_records() {
            // Fail at phase-2 send #3 (0-indexed): events [0, 1, 2] should land
            // in the mock, send_batch must return Err, and no event at index
            // >= 3 should ever hit the producer. Batch size is well above the
            // scatter-gather threshold so phase 2 runs post-parallel-prep.
            const BATCH: usize = 10;
            const FAIL_IDX: usize = 3;
            let producer = MockKafkaProducer::new_failing_at(FAIL_IDX);
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let events = build_batch(BATCH);
            let input_distinct_ids: Vec<String> =
                events.iter().map(|e| e.event.distinct_id.clone()).collect();

            let res = sink.send_batch(events).await;
            match res {
                Err(CaptureError::RetryableSinkError) => {}
                Err(other) => panic!("expected RetryableSinkError, got {other:?}"),
                Ok(()) => panic!("expected send_batch to fail on enqueue #{FAIL_IDX}"),
            }

            let records = producer.get_records();
            assert_eq!(
                records.len(),
                FAIL_IDX,
                "expected exactly {FAIL_IDX} records to reach producer before failure"
            );

            // Output distinct_ids should match input[..FAIL_IDX] in order:
            // phase-2 is serial in input order, so the earlier records must
            // be the first FAIL_IDX events of the input batch.
            let output_distinct_ids: Vec<String> = records
                .iter()
                .map(|r| {
                    let v: serde_json::Value =
                        serde_json::from_slice(&r.payload).expect("payload is valid json");
                    v.get("distinct_id")
                        .and_then(|u| u.as_str())
                        .expect("distinct_id field present")
                        .to_string()
                })
                .collect();
            assert_eq!(
                output_distinct_ids,
                input_distinct_ids[..FAIL_IDX],
                "earlier records must preserve input order on mid-batch failure"
            );
        }

        #[tokio::test]
        async fn send_batch_single_event_via_batch_path() {
            // batch_size=1 exercises the serial fast path (1 < SCATTER_GATHER_MIN_BATCH)
            // and verifies the loop handles a single-element batch correctly.
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let events = build_batch(1);
            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), 1, "expected exactly one record");
            assert_eq!(records[0].topic, MAIN_TOPIC);
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_just_below_threshold_uses_serial_path() {
            // batch_size = SCATTER_GATHER_MIN_BATCH - 1 takes the serial fast
            // path. We can't observe "which path ran" directly, so we assert
            // behavioral equivalence: N records, correct topic, input order.
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let size = SCATTER_GATHER_MIN_BATCH - 1;
            let events = build_batch(size);
            let input_distinct_ids: Vec<String> =
                events.iter().map(|e| e.event.distinct_id.clone()).collect();

            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), size);
            let output: Vec<String> = records
                .iter()
                .map(|r| {
                    let v: serde_json::Value =
                        serde_json::from_slice(&r.payload).expect("payload is valid json");
                    v["distinct_id"].as_str().unwrap().to_string()
                })
                .collect();
            assert_eq!(
                output, input_distinct_ids,
                "serial path must preserve order"
            );
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_at_threshold_uses_scatter_gather_path() {
            // batch_size = SCATTER_GATHER_MIN_BATCH takes the scatter-gather
            // path. Behavioral equivalence with the serial path must hold:
            // same N records, same order, same topics.
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let size = SCATTER_GATHER_MIN_BATCH;
            let events = build_batch(size);
            let input_distinct_ids: Vec<String> =
                events.iter().map(|e| e.event.distinct_id.clone()).collect();

            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), size);
            let output: Vec<String> = records
                .iter()
                .map(|r| {
                    let v: serde_json::Value =
                        serde_json::from_slice(&r.payload).expect("payload is valid json");
                    v["distinct_id"].as_str().unwrap().to_string()
                })
                .collect();
            assert_eq!(
                output, input_distinct_ids,
                "scatter-gather path must preserve input order after sort_unstable_by_key"
            );
        }

        // ==================== Sink mechanism seam ====================
        // The per-event result surface `Sink::publish` reports: uuid-aligned
        // with the input payloads, batch-uniform on failure. `fold_results`
        // discards this shape, so the send_batch tests above cannot see it —
        // and the outputs layer builds on it.

        #[tokio::test]
        async fn publish_reports_uuid_aligned_results() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let payloads = sink
                .prepare_batch(build_batch(3))
                .await
                .expect("prepare_batch failed");
            let input_uuids: Vec<_> = payloads.iter().map(|p| p.uuid).collect();

            let results = sink.publish(payloads).await;

            assert_eq!(results.len(), 3);
            for (result, uuid) in results.iter().zip(&input_uuids) {
                assert_eq!(result.uuid, *uuid, "results must align with input order");
                assert!(matches!(result.outcome, Outcome::Published));
            }
        }

        #[tokio::test]
        async fn publish_enqueue_failure_is_batch_uniform() {
            const FAIL_IDX: usize = 1;
            let producer = MockKafkaProducer::new_failing_at(FAIL_IDX);
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let payloads = sink
                .prepare_batch(build_batch(3))
                .await
                .expect("prepare_batch failed");
            let input_uuids: Vec<_> = payloads.iter().map(|p| p.uuid).collect();

            let results = sink.publish(payloads).await;

            // Every event reports the failure, the one enqueued before it
            // included; only the records before the failing index reached
            // the producer.
            assert_eq!(results.len(), 3);
            for (result, uuid) in results.iter().zip(&input_uuids) {
                assert_eq!(result.uuid, *uuid, "results must align with input order");
                assert!(matches!(
                    result.outcome,
                    Outcome::Failed(CaptureError::RetryableSinkError)
                ));
            }
            assert_eq!(producer.get_records().len(), FAIL_IDX);
        }

        #[tokio::test]
        async fn publish_ack_failure_is_batch_uniform() {
            const FAIL_IDX: usize = 1;
            let producer = MockKafkaProducer::new_failing_ack_at(FAIL_IDX);
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let payloads = sink
                .prepare_batch(build_batch(3))
                .await
                .expect("prepare_batch failed");
            let input_uuids: Vec<_> = payloads.iter().map(|p| p.uuid).collect();

            let results = sink.publish(payloads).await;

            // The producer accepted every record — all three were enqueued —
            // but one delivery report failed, so the whole batch reports the
            // failure, acked-before-failure events included.
            assert_eq!(results.len(), 3);
            for (result, uuid) in results.iter().zip(&input_uuids) {
                assert_eq!(result.uuid, *uuid, "results must align with input order");
                assert!(matches!(
                    result.outcome,
                    Outcome::Failed(CaptureError::RetryableSinkError)
                ));
            }
            assert_eq!(producer.get_records().len(), 3);
        }

        /// Per-event-type topic routing is covered by `assert_routing` for
        /// the single-event path. This test verifies routing survives the
        /// batch path for a mixed batch of data types plus one force_overflow
        /// AnalyticsMain — exercised on both the serial fast path (5 events)
        /// and the scatter-gather path (10 events).
        async fn mixed_datatypes_routing_for_batch(pad_to: usize) {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            // Core 5-event diverse batch.
            let mut events: Vec<ProcessedEvent> = vec![
                create_test_event(&EventInput {
                    data_type: DataType::AnalyticsMain,
                    ..EventInput::default()
                }),
                create_test_event(&EventInput {
                    data_type: DataType::HeatmapMain,
                    ..EventInput::default()
                }),
                create_test_event(&EventInput {
                    data_type: DataType::ExceptionErrorTracking,
                    ..EventInput::default()
                }),
                create_test_event(&EventInput {
                    data_type: DataType::ClientIngestionWarning,
                    ..EventInput::default()
                }),
                create_test_event(&EventInput {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: true,
                    ..EventInput::default()
                }),
            ];

            // Pad with AnalyticsMain events if caller wants to push the batch
            // over SCATTER_GATHER_MIN_BATCH. Padding goes at the end so the
            // first 5 per-event assertions line up regardless of batch size.
            while events.len() < pad_to {
                events.push(create_test_event(&EventInput::default()));
            }

            sink.send_batch(events).await.expect("send_batch failed");

            let records = producer.get_records();
            assert_eq!(records.len(), pad_to.max(5));

            // Per-index topic assertions (order-preserving: phase-2 is serial
            // in input order on both paths).
            assert_eq!(records[0].topic, MAIN_TOPIC, "event[0]: AnalyticsMain");
            assert_eq!(records[1].topic, HEATMAPS_TOPIC, "event[1]: HeatmapMain");
            assert_eq!(
                records[2].topic, ERROR_TRACKING_TOPIC,
                "event[2]: ExceptionErrorTracking"
            );
            assert_eq!(
                records[3].topic, CLIENT_INGESTION_WARNING_TOPIC,
                "event[3]: ClientIngestionWarning"
            );
            assert_eq!(
                records[4].topic, OVERFLOW_TOPIC,
                "event[4]: AnalyticsMain + force_overflow"
            );
        }

        #[tokio::test]
        async fn send_batch_mixed_datatypes_serial_path() {
            // 5 events < SCATTER_GATHER_MIN_BATCH => serial fast path.
            mixed_datatypes_routing_for_batch(5).await;
        }

        #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
        async fn send_batch_mixed_datatypes_scatter_gather_path() {
            // 10 events >= SCATTER_GATHER_MIN_BATCH => scatter-gather path.
            mixed_datatypes_routing_for_batch(10).await;
        }

        // ==================== Envelope compression ====================

        #[tokio::test]
        async fn snapshot_payload_uncompressed_by_default() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let event = create_test_event(&EventInput {
                data_type: DataType::SnapshotMain,
                ..Default::default()
            });
            sink.kafka_send(event).unwrap().await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1);
            // Payload must be valid UTF-8 JSON when compression is off.
            let v: serde_json::Value = serde_json::from_slice(&records[0].payload)
                .expect("uncompressed payload is valid json");
            assert!(v.get("distinct_id").is_some());
        }

        #[tokio::test]
        async fn snapshot_payload_lz4_compressed_when_enabled() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer_and_compression(
                producer.clone(),
                test_topics(),
                EnvelopeCompression::Lz4,
            );

            let event = create_test_event(&EventInput {
                data_type: DataType::SnapshotMain,
                ..Default::default()
            });
            sink.kafka_send(event).unwrap().await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1);
            // `content-encoding: lz4` header must be present.
            assert_eq!(
                records[0].headers.content_encoding.as_deref(),
                Some("lz4"),
                "expected content-encoding: lz4 header"
            );
            // Payload = 4-byte LE uncompressed size + LZ4 block data. Decompress and verify.
            let payload = &records[0].payload;
            let uncompressed_len = u32::from_le_bytes(payload[..4].try_into().unwrap()) as usize;
            let decompressed = lz4::block::decompress(&payload[4..], Some(uncompressed_len as i32))
                .expect("failed to decompress");
            let v: serde_json::Value =
                serde_json::from_slice(&decompressed).expect("decompressed payload is valid json");
            assert!(v.get("distinct_id").is_some());
        }

        #[tokio::test]
        async fn non_snapshot_payload_not_compressed_when_lz4_enabled() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer_and_compression(
                producer.clone(),
                test_topics(),
                EnvelopeCompression::Lz4,
            );

            let event = create_test_event(&EventInput {
                data_type: DataType::AnalyticsMain,
                ..Default::default()
            });
            sink.kafka_send(event).unwrap().await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1);
            // Non-snapshot payloads must stay uncompressed regardless of the flag.
            let v: serde_json::Value =
                serde_json::from_slice(&records[0].payload).expect("payload must be plain json");
            assert!(v.get("distinct_id").is_some());
        }
    }
}
