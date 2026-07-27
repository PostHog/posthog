//! Kafka sink: pure transport.
//!
//! The sink wraps a producer and publishes **realized records** — concrete
//! topic, partition key, payload bytes, headers — with an ordering-preserving
//! enqueue and a concurrent ack drain. It holds no topic table and reads no
//! event metadata: lane decisions happen in the pipeline layer, payload
//! assembly and namespace realization (Address → topic) in the outputs
//! layer. Anything that picks between destinations or backends is an
//! outputs-layer concern.
//!
//! Health reporting: the producer's rdkafka stats callback drives the
//! optional liveness handle (see [`KafkaContext`]); a sink built without a
//! handle still produces and emits metrics but does not gate the pod.
use crate::api::CaptureError;
use crate::config::KafkaConfig;
use crate::sinks::producer::{KafkaProducer, ProduceRecord};
use crate::sinks::sink::SinkResult;
use metrics::{counter, gauge, histogram};
use rdkafka::producer::{FutureProducer, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::task::JoinSet;
use tracing::log::{debug, error, info};
use tracing::{info_span, instrument, Instrument};
use uuid::Uuid;

use super::producer::RdKafkaProducer;

pub struct KafkaContext {
    /// Lifecycle handle this producer reports liveness to. `None` for a producer
    /// whose health must not gate the pod (e.g. the non-critical side of a
    /// split output) — it still produces and emits metrics, it just doesn't
    /// drive a manager component.
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

/// Generic Kafka sink that can use any producer implementation.
///
/// Holds the producer handle and this cluster's topic table. The sink makes
/// no routing decisions — the address on each payload is decided upstream —
/// but it owns realizing that address in its own cluster's namespace: the
/// same `Analytics(Overflow)` address may be a differently-named topic on a
/// failover cluster, and a repartitioning coordinator can re-point a lane by
/// swapping this table without any upstream change.
pub struct KafkaSinkBase<P: KafkaProducer> {
    producer: Arc<P>,
}

impl<P: KafkaProducer> Clone for KafkaSinkBase<P> {
    fn clone(&self) -> Self {
        Self {
            producer: Arc::clone(&self.producer),
        }
    }
}

/// A fully-realized produce record plus the correlation UUID of the event it
/// came from: everything above the sink is already decided — payload bytes,
/// headers, partition key, and the **concrete topic** (the outputs layer
/// realized the abstract `Address` in this cluster's namespace).
pub struct RealizedRecord {
    pub uuid: Uuid,
    pub record: ProduceRecord,
}

/// The default KafkaSink using rdkafka's FutureProducer
pub type KafkaSink = KafkaSinkBase<RdKafkaProducer<KafkaContext>>;

impl KafkaSink {
    pub async fn new(
        config: KafkaConfig,
        liveness: Option<lifecycle::Handle>,
    ) -> anyhow::Result<KafkaSink> {
        let producer = Self::connect(&config, liveness).await?;
        Ok(Self::from_parts(producer))
    }

    /// A sink over an already-connected producer — how multiple outputs share
    /// one cluster connection.
    pub fn from_parts(producer: Arc<RdKafkaProducer<KafkaContext>>) -> Self {
        KafkaSinkBase { producer }
    }

    /// Verify that every listed topic exists on this sink's cluster. Used by
    /// the opt-in boot check (`CAPTURE_VERIFY_TOPICS_ON_BOOT`); beware that
    /// on brokers with topic auto-creation the metadata probe itself can
    /// create the topic.
    pub fn verify_topics(&self, topics: &[&str]) -> anyhow::Result<()> {
        for topic in topics {
            let metadata = self
                .producer
                .client()
                .fetch_metadata(Some(topic), Timeout::After(Duration::new(10, 0)))
                .map_err(|e| anyhow::anyhow!("metadata fetch for topic '{topic}' failed: {e}"))?;
            let known = metadata
                .topics()
                .iter()
                .any(|t| t.name() == *topic && t.error().is_none() && !t.partitions().is_empty());
            anyhow::ensure!(
                known,
                "topic '{topic}' does not exist on this cluster (or has no partitions)"
            );
        }
        Ok(())
    }

    /// Connect a producer to the cluster in `config`. Shared by every sink
    /// that produces to that cluster.
    pub async fn connect(
        config: &KafkaConfig,
        liveness: Option<lifecycle::Handle>,
    ) -> anyhow::Result<Arc<RdKafkaProducer<KafkaContext>>> {
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

        let rd_producer = RdKafkaProducer::new(producer);

        Ok(Arc::new(rd_producer))
    }
}

impl<P: KafkaProducer> KafkaSinkBase<P> {
    /// Create a new KafkaSinkBase with a custom producer (useful for testing).
    /// No limiters — the sink is a mechanism layer; overflow stamping happens
    /// upstream in the pipeline. See the module header for details.
    pub fn with_producer(producer: P) -> Self {
        Self {
            producer: Arc::new(producer),
        }
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
}

// Batch machinery needs `P: 'static`: prep tasks and ack futures are spawned
// onto tokio workers, which require owned, static futures.
impl<P: KafkaProducer + 'static> KafkaSinkBase<P> {
    /// Serial, ordering-preserving enqueue of a prepared batch followed by the
    /// concurrent ack drain. Fail-fast on the first enqueue or ack error; the
    /// ordering bottleneck is deliberate — librdkafka preserves per-partition
    /// on-wire order by send_result() call order, and same-distinct_id events
    /// hash to the same partition via murmur2, so within-batch same-key
    /// ordering survives (e.g. $identify lands before subsequent events).
    async fn enqueue_and_drain(&self, records: Vec<ProduceRecord>) -> Result<(), CaptureError> {
        let enqueue_start = Instant::now();
        let mut ack_set = JoinSet::new();
        for record in records {
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
                    // capture_kafka_produce_ack_duration_ms. This mirrors the
                    // prep phase's explicit `prep_set.abort_all()`.
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
}

impl<P: KafkaProducer + 'static> KafkaSinkBase<P> {
    /// Publish a batch of realized records. The mechanism is fail-fast to
    /// preserve v0's whole-request semantics, so results are batch-uniform:
    /// all ok, or every record carrying the batch's error (acks for a failed
    /// batch are aborted, so no event can honestly claim success).
    #[instrument(skip_all)]
    pub async fn publish(&self, records: Vec<RealizedRecord>) -> Vec<SinkResult> {
        let (uuids, records): (Vec<Uuid>, Vec<ProduceRecord>) =
            records.into_iter().map(|r| (r.uuid, r.record)).unzip();
        match self.enqueue_and_drain(records).await {
            Ok(()) => uuids.into_iter().map(SinkResult::ok).collect(),
            Err(err) => uuids
                .into_iter()
                .map(|uuid| SinkResult::err(uuid, err.clone()))
                .collect(),
        }
    }

    pub fn flush(&self) -> Result<(), anyhow::Error> {
        self.producer.flush().map_err(|e| anyhow::anyhow!(e))
    }
}

/// The ack drain: concurrent, fail-fast on first ack error.
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
