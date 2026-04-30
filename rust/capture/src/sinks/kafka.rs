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
use crate::config::KafkaConfig;
use crate::sinks::producer::{KafkaProducer, ProduceRecord};
use crate::sinks::Event;
use crate::v0_request::{DataType, OverflowReason, ProcessedEvent};
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
    liveness: lifecycle::Handle,
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
            self.liveness.report_healthy();
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
        gauge!("capture_kafka_producer_queue_bytes",).set(stats.msg_max as f64);
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

/// Topic configuration for the Kafka sink
#[derive(Clone)]
pub struct KafkaTopicConfig {
    pub main_topic: String,
    pub overflow_topic: String,
    pub historical_topic: String,
    pub client_ingestion_warning_topic: String,
    pub heatmaps_topic: String,
    pub replay_overflow_topic: String,
    pub dlq_topic: String,
    pub error_tracking_topic: String,
    pub traces_topic: String,
}

impl From<&KafkaConfig> for KafkaTopicConfig {
    fn from(config: &KafkaConfig) -> Self {
        Self {
            main_topic: config.kafka_topic.clone(),
            overflow_topic: config.kafka_overflow_topic.clone(),
            historical_topic: config.kafka_historical_topic.clone(),
            client_ingestion_warning_topic: config.kafka_client_ingestion_warning_topic.clone(),
            heatmaps_topic: config.kafka_heatmaps_topic.clone(),
            replay_overflow_topic: config.kafka_replay_overflow_topic.clone(),
            dlq_topic: config.kafka_dlq_topic.clone(),
            error_tracking_topic: config.kafka_error_tracking_topic.clone(),
            traces_topic: config.kafka_traces_topic.clone(),
        }
    }
}

/// Generic Kafka sink that can use any producer implementation.
///
/// Holds only the producer handle and the topic config. No limiter state —
/// overflow and replay-overflow routing decisions are stamped upstream in the
/// pipeline onto `ProcessedEventMetadata::overflow_reason` and read here.
/// Both fields are `Arc` so `clone()` is two atomic ref-count increments,
/// which matters under the scatter-gather batch produce path where the sink
/// is cloned once per spawned prep task.
pub struct KafkaSinkBase<P: KafkaProducer> {
    producer: Arc<P>,
    topics: Arc<KafkaTopicConfig>,
}

impl<P: KafkaProducer> Clone for KafkaSinkBase<P> {
    fn clone(&self) -> Self {
        Self {
            producer: Arc::clone(&self.producer),
            topics: Arc::clone(&self.topics),
        }
    }
}

/// The default KafkaSink using rdkafka's FutureProducer
pub type KafkaSink = KafkaSinkBase<RdKafkaProducer<KafkaContext>>;

impl KafkaSink {
    pub async fn new(
        config: KafkaConfig,
        liveness: lifecycle::Handle,
    ) -> anyhow::Result<KafkaSink> {
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
            liveness.report_healthy();
            info!("connected to Kafka brokers");
        };

        let topics = Arc::new(KafkaTopicConfig::from(&config));
        let rd_producer = RdKafkaProducer::new(producer);

        Ok(KafkaSinkBase {
            producer: Arc::new(rd_producer),
            topics,
        })
    }
}

impl<P: KafkaProducer> KafkaSinkBase<P> {
    /// Create a new KafkaSinkBase with a custom producer (useful for testing).
    /// No limiters — the sink is a mechanism layer; overflow stamping happens
    /// upstream in the pipeline. See the module header for details.
    pub fn with_producer(producer: P, topics: KafkaTopicConfig) -> Self {
        Self {
            producer: Arc::new(producer),
            topics: Arc::new(topics),
        }
    }

    /// CPU-bound prep work: serialize payload + build headers + pick topic/key.
    /// Safe to run concurrently across events in a batch because it does not
    /// touch the librdkafka producer queue — phase 2 of `send_batch` is what
    /// enforces per-partition ordering by calling `enqueue_record` serially
    /// in the original event order.
    ///
    /// Routing policy is read from `ProcessedEventMetadata` (stamped upstream
    /// by the pipeline). This function does not consult any limiter — it is
    /// pure mechanism. DLQ and custom-topic redirects take priority over
    /// overflow routing, matching the pre-refactor ordering.
    ///
    /// Not `async`: post-refactor there are no await points, and keeping it
    /// synchronous lets `send_batch`'s serial fast path call it inline without
    /// any runtime indirection.
    fn prepare_record(&self, event: ProcessedEvent) -> Result<ProduceRecord, CaptureError> {
        let (event, metadata) = (event.event, event.metadata);

        let payload = serde_json::to_string(&event).map_err(|e| {
            error!("failed to serialize event: {e:#}");
            CaptureError::NonRetryableSinkError
        })?;

        let data_type = metadata.data_type;
        let event_key = event.key();
        let session_id = metadata.session_id.clone();
        let force_overflow = metadata.force_overflow;
        let skip_person_processing = metadata.skip_person_processing;
        let redirect_to_dlq = metadata.redirect_to_dlq;
        let redirect_to_topic = metadata.redirect_to_topic;
        let overflow_reason = metadata.overflow_reason;

        // Use the event's to_headers() method for consistent header serialization
        let mut headers = event.to_headers();

        drop(event); // Events can be EXTREMELY memory hungry

        // Apply skip_person_processing from event restrictions / upstream decisions
        if skip_person_processing {
            headers.set_force_disable_person_processing(true);
        }

        // Check for redirect_to_dlq first - takes priority over all other routing
        let (topic, partition_key): (&str, Option<&str>) = if redirect_to_dlq {
            counter!(
                "capture_events_rerouted_dlq",
                &[("reason", "event_restriction")]
            )
            .increment(1);

            // Set DLQ specific headers
            // DLQ reason cannot be known beyond being triggered by an event restriction.
            headers.set_dlq_reason("event_restriction".to_string());
            // Unlike with our node code, DLQ step will always be static.
            headers.set_dlq_step("capture".to_string());
            headers.set_dlq_timestamp(
                chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            );

            (&self.topics.dlq_topic, Some(event_key.as_str()))
        } else if let Some(ref topic) = redirect_to_topic {
            counter!(
                "capture_events_rerouted_custom_topic",
                &[("reason", "event_restriction")]
            )
            .increment(1);
            (topic.as_str(), Some(event_key.as_str()))
        } else {
            match data_type {
                DataType::AnalyticsHistorical => {
                    // Historical events never overflow — force_overflow and
                    // overflow_reason are deliberately ignored here.
                    (&self.topics.historical_topic, Some(event_key.as_str()))
                }
                DataType::AnalyticsMain => {
                    // Precedence: force_overflow (restrictions) -> overflow_reason
                    // (pipeline-stamped) -> default main-topic routing.
                    if force_overflow {
                        // Drop partition key if skip_person_processing is set
                        let key = if skip_person_processing {
                            None
                        } else {
                            Some(event_key.as_str())
                        };
                        (&self.topics.overflow_topic, key)
                    } else {
                        match &overflow_reason {
                            Some(OverflowReason::ForceLimited) => {
                                // Redundant with the generic skip-person path
                                // above (the pipeline stamps
                                // `metadata.skip_person_processing = true`
                                // alongside `OverflowReason::ForceLimited`), but
                                // kept as defense against a future caller that
                                // stamps the reason without the side-effect.
                                headers.set_force_disable_person_processing(true);
                                (&self.topics.overflow_topic, None)
                            }
                            Some(OverflowReason::RateLimited {
                                preserve_locality: true,
                            }) => (&self.topics.overflow_topic, Some(event_key.as_str())),
                            Some(OverflowReason::RateLimited {
                                preserve_locality: false,
                            }) => (&self.topics.overflow_topic, None),
                            // ReplayLimited never applies to AnalyticsMain; fall through to main.
                            Some(OverflowReason::ReplayLimited) | None => {
                                // Drop partition key if skip_person_processing is set
                                let key = if skip_person_processing {
                                    None
                                } else {
                                    Some(event_key.as_str())
                                };
                                (&self.topics.main_topic, key)
                            }
                        }
                    }
                }
                DataType::ClientIngestionWarning => (
                    &self.topics.client_ingestion_warning_topic,
                    Some(event_key.as_str()),
                ),
                DataType::HeatmapMain => (&self.topics.heatmaps_topic, Some(event_key.as_str())),
                DataType::ExceptionErrorTracking => {
                    (&self.topics.error_tracking_topic, Some(event_key.as_str()))
                }
                DataType::SnapshotMain => {
                    let session_id = session_id
                        .as_deref()
                        .ok_or(CaptureError::MissingSessionId)?;

                    // Precedence: force_overflow (restrictions) -> overflow_reason
                    // (pipeline-stamped ReplayLimited) -> default main-topic
                    // routing. Partition key is always session_id for replay
                    // to keep per-session ordering on the overflow topic.
                    if force_overflow
                        || matches!(overflow_reason, Some(OverflowReason::ReplayLimited))
                    {
                        (&self.topics.replay_overflow_topic, Some(session_id))
                    } else {
                        (&self.topics.main_topic, Some(session_id))
                    }
                }
            }
        };

        Ok(ProduceRecord {
            topic: topic.to_string(),
            key: partition_key.map(|s| s.to_string()),
            payload,
            headers,
        })
    }

    /// Serial, ordering-preserving enqueue into librdkafka. Emits the per-topic
    /// bytes counter and returns the ack future for the caller to await.
    /// librdkafka preserves on-wire partition order by `send_result` call order,
    /// so this MUST be called in the original event order within a batch.
    fn enqueue_record(&self, record: ProduceRecord) -> Result<P::AckFuture, CaptureError> {
        let payload_bytes = record.payload.len() as u64;
        counter!("capture_kafka_produce_bytes_total", "topic" => record.topic.clone())
            .increment(payload_bytes);
        self.producer.send(record)
    }

    /// Prep + enqueue for the single-event path. Retained as a thin wrapper so
    /// the `Event::send` impl stays unchanged; `send_batch` uses prepare_record
    /// and enqueue_record directly to parallelize the prep phase.
    fn kafka_send(&self, event: ProcessedEvent) -> Result<P::AckFuture, CaptureError> {
        let record = self.prepare_record(event)?;
        self.enqueue_record(record)
    }
}

/// Batches below this size take the serial fast path in `send_batch`: spawning
/// N `JoinSet` tasks to run `prepare_record` in parallel is net-negative when
/// each task does only a `serde_json::to_string` and a header build — the
/// scheduler overhead dominates the CPU savings. Scatter-gather kicks in at
/// or above this threshold where parallel prep wins back its spawn cost.
pub(crate) const SCATTER_GATHER_MIN_BATCH: usize = 8;

#[async_trait]
impl<P: KafkaProducer + 'static> Event for KafkaSinkBase<P> {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let ack_future = self.kafka_send(event)?;
        histogram!("capture_event_batch_size").record(1.0);
        ack_future.instrument(info_span!("ack_wait_one")).await
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let batch_size = events.len();
        // Record the batch-size histogram up front so the distribution is a
        // faithful view of batches submitted, not only those that succeeded.
        // Matches the single-event `send` path which records before any await.
        histogram!("capture_event_batch_size").record(batch_size as f64);

        // Small-batch fast path. For batches under `SCATTER_GATHER_MIN_BATCH`
        // the JoinSet spawn overhead dominates any parallel-prep win, so we
        // stay single-threaded. We keep the scatter-gather path's semantic
        // "prep error -> no records produced" by prepping all events first
        // into a Vec, then doing the serial enqueue phase only if all prep
        // succeeded. Both duration histograms are recorded so dashboards
        // keep a faithful view of the fast path.
        if batch_size < SCATTER_GATHER_MIN_BATCH {
            let prep_start = Instant::now();
            let mut prepared: Vec<ProduceRecord> = Vec::with_capacity(batch_size);
            for event in events {
                match self.prepare_record(event) {
                    Ok(record) => prepared.push(record),
                    Err(err) => {
                        histogram!("capture_kafka_batch_prep_duration_seconds")
                            .record(prep_start.elapsed().as_secs_f64());
                        return Err(err);
                    }
                }
            }
            histogram!("capture_kafka_batch_prep_duration_seconds")
                .record(prep_start.elapsed().as_secs_f64());

            let enqueue_start = Instant::now();
            let mut ack_set = JoinSet::new();
            for record in prepared {
                match self.enqueue_record(record) {
                    Ok(ack_future) => {
                        ack_set.spawn(ack_future);
                    }
                    Err(err) => {
                        // Dropping ack_set aborts any in-flight spawned ack
                        // futures; DeliveryAckFuture::drop records the
                        // "dropped" outcome on capture_kafka_produce_ack_duration_ms.
                        // Mirror of phase-2 behavior in the scatter-gather path.
                        histogram!("capture_kafka_batch_enqueue_duration_seconds")
                            .record(enqueue_start.elapsed().as_secs_f64());
                        return Err(err);
                    }
                }
            }
            histogram!("capture_kafka_batch_enqueue_duration_seconds")
                .record(enqueue_start.elapsed().as_secs_f64());

            return drain_acks(ack_set).await;
        }

        // Phase 1: parallel prep across tokio workers. Each task returns its
        // input index so we can reassemble results in the original event order
        // before the serial enqueue phase. This is where the CPU win lives:
        // serde_json::to_string + header build run concurrently on up to N
        // worker threads, rather than sequentially on a single task.
        let prep_start = Instant::now();
        let mut prep_set: JoinSet<(usize, Result<ProduceRecord, CaptureError>)> = JoinSet::new();
        for (idx, event) in events.into_iter().enumerate() {
            let this = self.clone();
            prep_set.spawn(
                async move { (idx, this.prepare_record(event)) }
                    .instrument(info_span!("prepare_record")),
            );
        }

        // Collect into a (idx, record) Vec and sort rather than indexing into
        // a `Vec<Option<ProduceRecord>>`. Encodes the "every slot filled"
        // invariant in the type: no `Option`, no unreachable `expect`, no
        // N-element `None` preallocation. Our only cancellation source is
        // `prep_set.abort_all()` below, invoked only from an already-errored
        // branch, so any `JoinError` observed during normal drain implies a
        // panic inside `prepare_record` — counted separately so it's alertable.
        let mut prepared: Vec<(usize, ProduceRecord)> = Vec::with_capacity(batch_size);
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
                Ok(record) => prepared.push((idx, record)),
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

        // Phase 2: serial enqueue in original event order. This is the ordering
        // bottleneck we deliberately keep: librdkafka preserves per-partition
        // on-wire order by send_result() call order, and same-distinct_id events
        // hash to the same partition via murmur2. Within-batch same-key ordering
        // must survive so e.g. $identify lands before subsequent events.
        let enqueue_start = Instant::now();
        let mut ack_set = JoinSet::new();
        for (_, record) in prepared {
            match self.enqueue_record(record) {
                Ok(ack_future) => {
                    ack_set.spawn(ack_future);
                }
                Err(err) => {
                    // Record enqueue duration on the error path too so slow-fail
                    // cases (e.g. QueueFull after a long stall) stay observable.
                    // Dropping `ack_set` when we return Err aborts any already
                    // spawned ack futures for this batch; DeliveryAckFuture::drop
                    // then records the "dropped" outcome on
                    // capture_kafka_produce_ack_duration_ms. This is the phase-2
                    // mirror of phase-1's explicit `prep_set.abort_all()`.
                    histogram!("capture_kafka_batch_enqueue_duration_seconds")
                        .record(enqueue_start.elapsed().as_secs_f64());
                    return Err(err);
                }
            }
        }
        histogram!("capture_kafka_batch_enqueue_duration_seconds")
            .record(enqueue_start.elapsed().as_secs_f64());

        drain_acks(ack_set).await
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        self.producer.flush().map_err(|e| anyhow::anyhow!(e))
    }
}

/// Phase 3 of `send_batch`: concurrent ack drain, fail-fast on first ack error.
/// Shared between the scatter-gather path and the small-batch serial fast path
/// so both converge on the same fail-fast + abort-siblings semantics. Dropping
/// the JoinSet on error aborts remaining spawned ack futures; DeliveryAckFuture
/// Drop then records the "dropped" outcome on capture_kafka_produce_ack_duration_ms.
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

/// Shared `KafkaTopicConfig` fixture for tests across the capture crate. Used
/// by sink-side routing tests and pipeline-to-sink E2E tests to ensure every
/// test site asserts against the same canonical topic names.
#[cfg(test)]
pub(crate) fn test_topics() -> KafkaTopicConfig {
    KafkaTopicConfig {
        main_topic: "events_plugin_ingestion".to_string(),
        overflow_topic: "events_plugin_ingestion_overflow".to_string(),
        historical_topic: "events_plugin_ingestion_historical".to_string(),
        client_ingestion_warning_topic: "client_ingestion_warning".to_string(),
        heatmaps_topic: "heatmaps".to_string(),
        replay_overflow_topic: "replay_overflow".to_string(),
        dlq_topic: "events_plugin_ingestion_dlq".to_string(),
        error_tracking_topic: "error_tracking_events".to_string(),
        traces_topic: "tracing_ingestion".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use crate::api::CaptureError;
    use crate::config;
    use crate::sinks::kafka::KafkaSink;
    use crate::sinks::Event;
    use crate::utils::uuid_v7;
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
            kafka_traces_topic: "traces_ingestion".to_string(),
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
        };
        let sink = KafkaSink::new(config, handle)
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
        let event: CapturedEvent = CapturedEvent {
            uuid: uuid_v7(),
            distinct_id: distinct_id.clone(),
            session_id: None,
            ip: "".to_string(),
            data: "".to_string(),
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            event: "test_event".to_string(),
            timestamp: chrono::Utc::now(),
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
            overflow_reason: None,
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
        let captured = CapturedEvent {
            uuid: uuid_v7(),
            distinct_id: "id1".to_string(),
            session_id: None,
            ip: "".to_string(),
            data: big_data,
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            event: "test_event".to_string(),
            timestamp: chrono::Utc::now(),
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

        let big_event = ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7(),
                distinct_id: "id1".to_string(),
                session_id: None,
                ip: "".to_string(),
                data: big_data,
                now: "".to_string(),
                sent_at: None,
                token: "token1".to_string(),
                event: "test_event".to_string(),
                timestamp: chrono::Utc::now(),
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
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
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
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
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
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
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
            dlq_reason: Some("test reason".to_string()),
            dlq_step: Some("test step".to_string()),
            dlq_timestamp: Some(dlq_timestamp.clone()),
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

        const MAIN_TOPIC: &str = "events_plugin_ingestion";
        const OVERFLOW_TOPIC: &str = "events_plugin_ingestion_overflow";
        const DLQ_TOPIC: &str = "events_plugin_ingestion_dlq";
        const HISTORICAL_TOPIC: &str = "events_plugin_ingestion_historical";
        const HEATMAPS_TOPIC: &str = "heatmaps";
        const CLIENT_INGESTION_WARNING_TOPIC: &str = "client_ingestion_warning";
        const REPLAY_OVERFLOW_TOPIC: &str = "replay_overflow";
        const ERROR_TRACKING_TOPIC: &str = "error_tracking_events";

        struct EventInput {
            data_type: DataType,
            force_overflow: bool,
            skip_person_processing: bool,
            redirect_to_dlq: bool,
            redirect_to_topic: Option<String>,
            overflow_reason: Option<OverflowReason>,
        }

        impl Default for EventInput {
            fn default() -> Self {
                Self {
                    data_type: DataType::AnalyticsMain,
                    force_overflow: false,
                    skip_person_processing: false,
                    redirect_to_dlq: false,
                    redirect_to_topic: None,
                    overflow_reason: None,
                }
            }
        }

        fn create_test_event(input: &EventInput) -> ProcessedEvent {
            let event = CapturedEvent {
                uuid: uuid_v7(),
                distinct_id: "test_user".to_string(),
                session_id: Some("session123".to_string()),
                ip: "127.0.0.1".to_string(),
                data: "{}".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                event: "test_event".to_string(),
                timestamp: chrono::Utc::now(),
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
                overflow_reason: input.overflow_reason.clone(),
            };

            ProcessedEvent { event, metadata }
        }

        struct ExpectedRouting<'a> {
            topic: &'a str,
            has_key: bool,
            force_disable_person_processing: Option<bool>,
        }

        async fn assert_routing(input: EventInput, expected: ExpectedRouting<'_>) {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let event = create_test_event(&input);
            sink.send(event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1, "Expected exactly one record");
            assert_eq!(
                records[0].topic,
                expected.topic,
                "Wrong topic for {:?} (overflow={}, skip_person={}, dlq={})",
                input.data_type,
                input.force_overflow,
                input.skip_person_processing,
                input.redirect_to_dlq
            );
            assert_eq!(
                records[0].key.is_some(),
                expected.has_key,
                "Wrong key presence for {:?} (overflow={}, skip_person={}, dlq={})",
                input.data_type,
                input.force_overflow,
                input.skip_person_processing,
                input.redirect_to_dlq
            );
            assert_eq!(
                records[0].headers.force_disable_person_processing,
                expected.force_disable_person_processing,
                "Wrong header for {:?} (overflow={}, skip_person={}, dlq={})",
                input.data_type,
                input.force_overflow,
                input.skip_person_processing,
                input.redirect_to_dlq
            );
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
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: HISTORICAL_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: REPLAY_OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: REPLAY_OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: HEATMAPS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: ERROR_TRACKING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: CLIENT_INGESTION_WARNING_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                },
            )
            .await;
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
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: None,
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
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: Some(true),
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
                },
                ExpectedRouting {
                    topic: "custom_topic",
                    has_key: true,
                    force_disable_person_processing: None,
                },
            )
            .await;
        }

        // ==================== DLQ Header Tests ====================
        // Verify that DLQ-specific headers (reason, step, timestamp) are set
        // when routing to DLQ, and absent for all other routes.

        #[tokio::test]
        async fn dlq_headers_set_when_redirect_to_dlq() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let event = create_test_event(&EventInput {
                data_type: DataType::AnalyticsMain,
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: true,
                redirect_to_topic: None,
                overflow_reason: None,
            });
            sink.send(event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1);
            let headers = &records[0].headers;

            assert_eq!(headers.dlq_reason.as_deref(), Some("event_restriction"));
            assert_eq!(headers.dlq_step.as_deref(), Some("capture"));
            assert!(
                headers.dlq_timestamp.is_some(),
                "dlq_timestamp should be set"
            );

            // Verify the timestamp is a valid RFC 3339 string
            let ts = headers.dlq_timestamp.as_deref().unwrap();
            chrono::DateTime::parse_from_rfc3339(ts)
                .unwrap_or_else(|e| panic!("dlq_timestamp '{ts}' is not valid RFC 3339: {e}"));
        }

        #[tokio::test]
        async fn dlq_headers_absent_for_normal_analytics() {
            let producer = MockKafkaProducer::new();
            let sink = KafkaSinkBase::with_producer(producer.clone(), test_topics());

            let event = create_test_event(&EventInput {
                data_type: DataType::AnalyticsMain,
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: false,
                redirect_to_topic: None,
                overflow_reason: None,
            });
            sink.send(event).await.unwrap();

            let records = producer.get_records();
            let headers = &records[0].headers;
            assert_eq!(headers.dlq_reason, None);
            assert_eq!(headers.dlq_step, None);
            assert_eq!(headers.dlq_timestamp, None);
        }

        // ==================== overflow_reason routing tests ====================
        // The pipeline stamps ProcessedEventMetadata::overflow_reason upstream;
        // the sink is a pure mechanism layer that switches on it. These cover
        // each variant: ForceLimited, RateLimited { preserve_locality }, and
        // ReplayLimited. `force_overflow` coexistence is covered by the
        // analytics_main_force_overflow / snapshot_main_force_overflow cases
        // above (force_overflow short-circuits the overflow_reason branch).

        #[tokio::test]
        async fn overflow_reason_force_limited_routes_to_overflow_with_null_key_and_flag() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    overflow_reason: Some(OverflowReason::ForceLimited),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: false,
                    force_disable_person_processing: Some(true),
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_rate_limited_preserves_key_when_preserve_locality() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    overflow_reason: Some(OverflowReason::RateLimited {
                        preserve_locality: true,
                    }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_rate_limited_drops_key_when_not_preserve_locality() {
            assert_routing(
                EventInput {
                    data_type: DataType::AnalyticsMain,
                    overflow_reason: Some(OverflowReason::RateLimited {
                        preserve_locality: false,
                    }),
                    ..Default::default()
                },
                ExpectedRouting {
                    topic: OVERFLOW_TOPIC,
                    has_key: false,
                    force_disable_person_processing: None,
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
                },
            )
            .await;
        }

        #[tokio::test]
        async fn overflow_reason_redirect_to_dlq_wins_over_overflow_reason() {
            // DLQ routing is the highest-priority routing decision: it wins
            // over both force_overflow and overflow_reason.
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
                    force_disable_person_processing: None,
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
                    force_disable_person_processing: None,
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
                        serde_json::from_str(&r.payload).expect("payload is valid json");
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
                        serde_json::from_str(&r.payload).expect("payload is valid json");
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
                        serde_json::from_str(&r.payload).expect("payload is valid json");
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
                        serde_json::from_str(&r.payload).expect("payload is valid json");
                    v["distinct_id"].as_str().unwrap().to_string()
                })
                .collect();
            assert_eq!(
                output, input_distinct_ids,
                "scatter-gather path must preserve input order after sort_unstable_by_key"
            );
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
    }
}
