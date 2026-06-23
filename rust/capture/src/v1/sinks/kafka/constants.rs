// ---------------------------------------------------------------------------
// Kafka sink metric keys
// ---------------------------------------------------------------------------

/// Per-event outcome counter (success, retriable, fatal, timeout).
pub(super) const KAFKA_PUBLISH_TOTAL: &str = "capture_v1_kafka_publish_total";

/// Per-event broker-ack latency histogram.
pub(super) const KAFKA_ACK_DURATION_SECONDS: &str = "capture_v1_kafka_ack_duration_seconds";

/// Per-batch enqueue wall-time histogram.
pub(super) const KAFKA_ENQUEUE_DURATION_SECONDS: &str = "capture_v1_kafka_enqueue_duration_seconds";

/// Produce-level error counter (distinct from ack errors).
pub(super) const KAFKA_PRODUCE_ERRORS_TOTAL: &str = "capture_v1_kafka_produce_errors_total";

/// Client-level rdkafka error counter.
pub(super) const KAFKA_CLIENT_ERRORS_TOTAL: &str = "capture_v1_kafka_client_errors_total";

/// Producer internal queue depth gauge (messages).
pub(super) const KAFKA_PRODUCER_QUEUE_DEPTH: &str = "capture_v1_kafka_producer_queue_depth";

/// Producer internal queue size gauge (bytes).
pub(super) const KAFKA_PRODUCER_QUEUE_BYTES: &str = "capture_v1_kafka_producer_queue_bytes";

/// Producer queue utilization gauge (0.0–1.0).
pub(super) const KAFKA_PRODUCER_QUEUE_UTILIZATION: &str =
    "capture_v1_kafka_producer_queue_utilization";

/// Average batch size (bytes) gauge from rdkafka stats.
pub(super) const KAFKA_BATCH_SIZE_BYTES_AVG: &str = "capture_v1_kafka_batch_size_bytes_avg";

/// Connected brokers gauge.
pub(super) const KAFKA_BROKER_CONNECTED: &str = "capture_v1_kafka_broker_connected";

/// Broker round-trip time (microseconds) histogram.
pub(super) const KAFKA_BROKER_RTT_US: &str = "capture_v1_kafka_broker_rtt_us";

/// Broker internal latency (microseconds) histogram.
pub(super) const KAFKA_BROKER_INT_LATENCY_US: &str = "capture_v1_kafka_broker_int_latency_us";

/// Broker outbound buffer latency (microseconds) histogram.
pub(super) const KAFKA_BROKER_OUTBUF_LATENCY_US: &str = "capture_v1_kafka_broker_outbuf_latency_us";

/// Broker TX error counter.
pub(super) const KAFKA_BROKER_TX_ERRORS_TOTAL: &str = "capture_v1_kafka_broker_tx_errors_total";

/// Broker RX error counter.
pub(super) const KAFKA_BROKER_RX_ERRORS_TOTAL: &str = "capture_v1_kafka_broker_rx_errors_total";
