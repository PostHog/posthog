use crate::avro_schema::AVRO_SCHEMA;
use crate::log_record::{sum_kafka_log_row_bytes, KafkaLogRow};
use crate::metric_record::KafkaMetricRow;
use crate::metrics_avro_schema::METRICS_AVRO_SCHEMA;
use crate::trace_record::KafkaTraceRow;
use crate::traces_avro_schema::TRACES_AVRO_SCHEMA;
use anyhow::anyhow;
use apache_avro::{Codec, Schema, Writer, ZstandardSettings};
use capture::config::KafkaConfig;
use chrono::Utc;
use health::HealthHandle;
use metrics::{counter, gauge};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use std::result::Result::Ok;
use std::time::Duration;
use tracing::log::{debug, info};

// Headroom left below the configured `message.max.bytes` for Kafka framing and
// our per-message headers, so a payload we accept locally doesn't get rejected
// once the record batch overhead is added.
const KAFKA_MESSAGE_OVERHEAD_BYTES: usize = 4096;

/// Error returned when producing an Avro batch to Kafka.
///
/// `MessageTooLarge` is separated out so the HTTP layer can answer 413 instead
/// of a generic 500: the payload can never succeed as-is, unlike transient
/// broker failures.
#[derive(Debug, thiserror::Error)]
pub enum WriteError {
    #[error("payload exceeds Kafka message size limit")]
    MessageTooLarge,
    #[error(transparent)]
    Other(#[from] anyhow::Error),
}

fn map_produce_error(err: KafkaError) -> WriteError {
    if err.rdkafka_error_code() == Some(RDKafkaErrorCode::MessageSizeTooLarge) {
        WriteError::MessageTooLarge
    } else {
        WriteError::Other(anyhow!("kafka error: {err}"))
    }
}

struct EncodedChunk {
    payload: Vec<u8>,
    row_count: usize,
}

fn encode_avro<T: serde::Serialize>(schema: &Schema, rows: &[T]) -> anyhow::Result<Vec<u8>> {
    let mut writer = Writer::with_codec(
        schema,
        Vec::new(),
        Codec::Zstandard(ZstandardSettings::new(1)),
    );
    for row in rows {
        writer.append_ser(row)?;
    }
    Ok(writer.into_inner()?)
}

/// Encode `rows` into one or more Avro payloads that each fit under `payload_limit`,
/// splitting the batch in half as needed. A single row that still exceeds the
/// limit cannot be split and yields `WriteError::MessageTooLarge`.
fn encode_chunks<T: serde::Serialize>(
    schema: &Schema,
    rows: &[T],
    payload_limit: usize,
    out: &mut Vec<EncodedChunk>,
) -> Result<(), WriteError> {
    let payload = encode_avro(schema, rows).map_err(WriteError::Other)?;
    if payload.len() <= payload_limit || rows.len() <= 1 {
        if payload.len() > payload_limit {
            return Err(WriteError::MessageTooLarge);
        }
        out.push(EncodedChunk {
            payload,
            row_count: rows.len(),
        });
        return Ok(());
    }

    let mid = rows.len() / 2;
    encode_chunks(schema, &rows[..mid], payload_limit, out)?;
    encode_chunks(schema, &rows[mid..], payload_limit, out)?;
    Ok(())
}

/// Distribute a batch-level counter across chunks proportionally to their row
/// counts, giving the final chunk the remainder so the parts sum to the whole.
fn split_share(remaining: u64, chunk_rows: usize, remaining_rows: usize, is_last: bool) -> u64 {
    if is_last || remaining_rows == 0 {
        remaining
    } else {
        ((remaining as u128 * chunk_rows as u128) / remaining_rows as u128) as u64
    }
}

struct KafkaContext {
    liveness: HealthHandle,
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, stats: rdkafka::Statistics) {
        // Signal liveness, as the main rdkafka loop is running and calling us
        let brokers_up = stats.brokers.values().any(|broker| broker.state == "UP");
        if brokers_up {
            self.liveness.report_healthy_blocking();
        }

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
            if let Some(rtt) = stats.rtt {
                gauge!(
                    "capture_kafka_produce_rtt_latency_us",
                    "quantile" => "p50",
                    "broker" => id_string.clone()
                )
                .set(rtt.p50 as f64);
                gauge!(
                    "capture_kafka_produce_rtt_latency_us",
                    "quantile" => "p90",
                    "broker" => id_string.clone()
                )
                .set(rtt.p90 as f64);
                gauge!(
                    "capture_kafka_produce_rtt_latency_us",
                    "quantile" => "p95",
                    "broker" => id_string.clone()
                )
                .set(rtt.p95 as f64);
                gauge!(
                    "capture_kafka_produce_rtt_latency_us",
                    "quantile" => "p99",
                    "broker" => id_string.clone()
                )
                .set(rtt.p99 as f64);
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

#[derive(Clone)]
pub struct KafkaSink {
    logs_producer: FutureProducer<KafkaContext>,
    traces_producer: FutureProducer<KafkaContext>,
    metrics_producer: FutureProducer<KafkaContext>,
    logs_topic: String,
    traces_topic: String,
    metrics_topic: String,
    logs_message_max_bytes: usize,
    traces_message_max_bytes: usize,
    metrics_message_max_bytes: usize,
}

#[allow(clippy::too_many_arguments)]
fn build_client_config(
    bootstrap_servers: &str,
    tls: bool,
    client_id: &str,
    compression_codec: &str,
    producer_acks: &str,
    producer_linger_ms: u32,
    producer_queue_mib: u32,
    message_timeout_ms: u32,
    producer_message_max_bytes: u32,
    producer_max_retries: u32,
    topic_metadata_refresh_interval_ms: u32,
    metadata_max_age_ms: u32,
) -> ClientConfig {
    let mut client_config = ClientConfig::new();
    client_config
        .set("bootstrap.servers", bootstrap_servers)
        .set("statistics.interval.ms", "10000")
        .set("partitioner", "murmur2_random") // Compatibility with python-kafka
        .set("metadata.max.age.ms", metadata_max_age_ms.to_string())
        .set(
            "topic.metadata.refresh.interval.ms",
            topic_metadata_refresh_interval_ms.to_string(),
        )
        .set("message.send.max.retries", producer_max_retries.to_string())
        .set("linger.ms", producer_linger_ms.to_string())
        .set("message.max.bytes", producer_message_max_bytes.to_string())
        .set("message.timeout.ms", message_timeout_ms.to_string())
        .set("compression.codec", compression_codec)
        .set(
            "queue.buffering.max.kbytes",
            (producer_queue_mib * 1024).to_string(),
        )
        .set("acks", producer_acks);

    if !client_id.is_empty() {
        client_config.set("client.id", client_id);
    }

    if tls {
        client_config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }

    client_config
}

async fn build_producer(
    client_config: ClientConfig,
    liveness: HealthHandle,
    label: &str,
) -> anyhow::Result<FutureProducer<KafkaContext>> {
    debug!("rdkafka {label} configuration: {client_config:?}");
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
        liveness.report_healthy().await;
        info!("connected to Kafka brokers ({label})");
    };

    Ok(producer)
}

impl KafkaSink {
    pub async fn new(
        config: KafkaConfig,
        logs_liveness: HealthHandle,
        traces_liveness: HealthHandle,
        metrics_liveness: HealthHandle,
    ) -> anyhow::Result<KafkaSink> {
        info!(
            "connecting to logs Kafka brokers at {}...",
            config.kafka_hosts
        );
        let logs_client_config = build_client_config(
            &config.kafka_hosts,
            config.kafka_tls,
            &config.kafka_client_id,
            &config.kafka_compression_codec,
            &config.kafka_producer_acks,
            config.kafka_producer_linger_ms,
            config.kafka_producer_queue_mib,
            config.kafka_message_timeout_ms,
            config.kafka_producer_message_max_bytes,
            config.kafka_producer_max_retries,
            config.kafka_topic_metadata_refresh_interval_ms,
            config.kafka_metadata_max_age_ms,
        );
        let logs_producer = build_producer(logs_client_config, logs_liveness, "logs").await?;

        let traces_hosts = config
            .kafka_traces_hosts
            .clone()
            .unwrap_or_else(|| config.kafka_hosts.clone());
        info!("connecting to traces Kafka brokers at {}...", traces_hosts);
        let traces_client_config = build_client_config(
            &traces_hosts,
            config.kafka_traces_tls.unwrap_or(config.kafka_tls),
            &config
                .kafka_traces_client_id
                .clone()
                .unwrap_or_else(|| config.kafka_client_id.clone()),
            &config
                .kafka_traces_compression_codec
                .clone()
                .unwrap_or_else(|| config.kafka_compression_codec.clone()),
            &config
                .kafka_traces_producer_acks
                .clone()
                .unwrap_or_else(|| config.kafka_producer_acks.clone()),
            config
                .kafka_traces_producer_linger_ms
                .unwrap_or(config.kafka_producer_linger_ms),
            config
                .kafka_traces_producer_queue_mib
                .unwrap_or(config.kafka_producer_queue_mib),
            config
                .kafka_traces_message_timeout_ms
                .unwrap_or(config.kafka_message_timeout_ms),
            config
                .kafka_traces_producer_message_max_bytes
                .unwrap_or(config.kafka_producer_message_max_bytes),
            config
                .kafka_traces_producer_max_retries
                .unwrap_or(config.kafka_producer_max_retries),
            config
                .kafka_traces_topic_metadata_refresh_interval_ms
                .unwrap_or(config.kafka_topic_metadata_refresh_interval_ms),
            config
                .kafka_traces_metadata_max_age_ms
                .unwrap_or(config.kafka_metadata_max_age_ms),
        );
        let traces_producer =
            build_producer(traces_client_config, traces_liveness, "traces").await?;

        let metrics_hosts = config
            .kafka_metrics_hosts
            .clone()
            .unwrap_or_else(|| config.kafka_hosts.clone());
        info!(
            "connecting to metrics Kafka brokers at {}...",
            metrics_hosts
        );
        let metrics_client_config = build_client_config(
            &metrics_hosts,
            config.kafka_metrics_tls.unwrap_or(config.kafka_tls),
            &config
                .kafka_metrics_client_id
                .clone()
                .unwrap_or_else(|| config.kafka_client_id.clone()),
            &config
                .kafka_metrics_compression_codec
                .clone()
                .unwrap_or_else(|| config.kafka_compression_codec.clone()),
            &config
                .kafka_metrics_producer_acks
                .clone()
                .unwrap_or_else(|| config.kafka_producer_acks.clone()),
            config
                .kafka_metrics_producer_linger_ms
                .unwrap_or(config.kafka_producer_linger_ms),
            config
                .kafka_metrics_producer_queue_mib
                .unwrap_or(config.kafka_producer_queue_mib),
            config
                .kafka_metrics_message_timeout_ms
                .unwrap_or(config.kafka_message_timeout_ms),
            config
                .kafka_metrics_producer_message_max_bytes
                .unwrap_or(config.kafka_producer_message_max_bytes),
            config
                .kafka_metrics_producer_max_retries
                .unwrap_or(config.kafka_producer_max_retries),
            config
                .kafka_metrics_topic_metadata_refresh_interval_ms
                .unwrap_or(config.kafka_topic_metadata_refresh_interval_ms),
            config
                .kafka_metrics_metadata_max_age_ms
                .unwrap_or(config.kafka_metadata_max_age_ms),
        );
        let metrics_producer =
            build_producer(metrics_client_config, metrics_liveness, "metrics").await?;

        Ok(KafkaSink {
            logs_producer,
            traces_producer,
            metrics_producer,
            logs_topic: config.kafka_topic,
            traces_topic: config.kafka_traces_topic,
            metrics_topic: config.kafka_metrics_topic,
            logs_message_max_bytes: config.kafka_producer_message_max_bytes as usize,
            traces_message_max_bytes: config
                .kafka_traces_producer_message_max_bytes
                .unwrap_or(config.kafka_producer_message_max_bytes)
                as usize,
            metrics_message_max_bytes: config
                .kafka_metrics_producer_message_max_bytes
                .unwrap_or(config.kafka_producer_message_max_bytes)
                as usize,
        })
    }

    pub fn flush(&self) -> Result<(), KafkaError> {
        // TODO: hook it up on shutdown
        self.logs_producer.flush(Duration::new(30, 0))?;
        self.traces_producer.flush(Duration::new(30, 0))?;
        self.metrics_producer.flush(Duration::new(30, 0))
    }

    #[allow(clippy::too_many_arguments)]
    async fn write_avro_batch<T: serde::Serialize>(
        &self,
        producer: &FutureProducer<KafkaContext>,
        topic: &str,
        avro_schema_str: &str,
        token: &str,
        rows: &[T],
        uncompressed_bytes: u64,
        records_uncompressed_bytes: Option<u64>,
        timestamps_overridden: u64,
        message_max_bytes: usize,
    ) -> Result<(), WriteError> {
        let schema = Schema::parse_str(avro_schema_str).map_err(|e| WriteError::Other(e.into()))?;
        let payload_limit = message_max_bytes
            .saturating_sub(KAFKA_MESSAGE_OVERHEAD_BYTES)
            .max(1);

        let mut chunks: Vec<EncodedChunk> = Vec::new();
        encode_chunks(&schema, rows, payload_limit, &mut chunks)?;

        if chunks.len() > 1 {
            counter!("capture_logs_kafka_batch_split_total").increment(1);
        }

        // Split the batch-level counters across chunks so billing headers still
        // sum to the values for the original request.
        let mut remaining_rows = rows.len();
        let mut remaining_uncompressed = uncompressed_bytes;
        let mut remaining_records = records_uncompressed_bytes;
        let mut remaining_ts = timestamps_overridden;

        for chunk in &chunks {
            let chunk_rows = chunk.row_count;
            let is_last = chunk_rows >= remaining_rows;

            let chunk_uncompressed =
                split_share(remaining_uncompressed, chunk_rows, remaining_rows, is_last);
            remaining_uncompressed -= chunk_uncompressed;

            let chunk_records = remaining_records.map(|r| {
                let share = split_share(r, chunk_rows, remaining_rows, is_last);
                remaining_records = Some(r - share);
                share
            });

            let chunk_ts = split_share(remaining_ts, chunk_rows, remaining_rows, is_last);
            remaining_ts -= chunk_ts;

            remaining_rows -= chunk_rows;

            self.send_encoded(
                producer,
                topic,
                token,
                &chunk.payload,
                chunk_uncompressed,
                chunk_records,
                chunk_rows,
                chunk_ts,
            )
            .await?;
        }

        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    async fn send_encoded(
        &self,
        producer: &FutureProducer<KafkaContext>,
        topic: &str,
        token: &str,
        payload: &[u8],
        uncompressed_bytes: u64,
        records_uncompressed_bytes: Option<u64>,
        record_count: usize,
        timestamps_overridden: u64,
    ) -> Result<(), WriteError> {
        let future = match producer.send_result(FutureRecord {
            topic,
            payload: Some(payload),
            partition: None,
            key: None::<Vec<u8>>.as_ref(),
            timestamp: None,
            headers: Some({
                let created_at = Utc::now().to_rfc3339();
                let mut headers = OwnedHeaders::new()
                    .insert(Header {
                        key: "token",
                        value: Some(&token.to_string()),
                    })
                    .insert(Header {
                        key: "bytes_uncompressed",
                        value: Some(&uncompressed_bytes.to_string()),
                    });
                // Records-based size next to the payload-based `bytes_uncompressed`, so
                // billing can compare the two before switching to the records-based value.
                if let Some(records_bytes) = records_uncompressed_bytes {
                    headers = headers.insert(Header {
                        key: "bytes_uncompressed_records",
                        value: Some(&records_bytes.to_string()),
                    });
                }
                headers
                    .insert(Header {
                        key: "bytes_compressed",
                        value: Some(&payload.len().to_string()),
                    })
                    .insert(Header {
                        key: "record_count",
                        value: Some(&record_count.to_string()),
                    })
                    .insert(Header {
                        key: "created_at",
                        value: Some(&created_at),
                    })
                    .insert(Header {
                        key: "batch_uuid",
                        value: Some(&uuid::Uuid::new_v4().to_string()),
                    })
                    .insert(Header {
                        key: "timestamps_overridden",
                        value: Some(&timestamps_overridden.to_string()),
                    })
            }),
        }) {
            Err((err, _)) => return Err(map_produce_error(err)),
            Ok(delivery_future) => delivery_future,
        };

        match future.await {
            Ok(Ok(_)) => Ok(()),
            Ok(Err((err, _))) => Err(map_produce_error(err)),
            Err(canceled) => Err(WriteError::Other(anyhow!(
                "kafka delivery canceled: {canceled}"
            ))),
        }
    }

    pub async fn write(
        &self,
        token: &str,
        rows: Vec<KafkaLogRow>,
        uncompressed_bytes: u64,
        timestamps_overridden: u64,
    ) -> Result<(), WriteError> {
        if rows.is_empty() {
            return Ok(());
        }

        if timestamps_overridden > 0 {
            counter!("capture_logs_timestamps_overridden").increment(timestamps_overridden);
        }

        let records_uncompressed_bytes = sum_kafka_log_row_bytes(&rows);
        counter!("capture_logs_bytes_uncompressed_payload").increment(uncompressed_bytes);
        counter!("capture_logs_bytes_uncompressed_records").increment(records_uncompressed_bytes);
        if records_uncompressed_bytes > uncompressed_bytes {
            // Records sum should stay below the payload size (it excludes transport overhead);
            // billing can only switch to it if that invariant holds.
            counter!("capture_logs_records_bytes_exceed_payload").increment(1);
        }

        self.write_avro_batch(
            &self.logs_producer,
            &self.logs_topic,
            AVRO_SCHEMA,
            token,
            &rows,
            uncompressed_bytes,
            Some(records_uncompressed_bytes),
            timestamps_overridden,
            self.logs_message_max_bytes,
        )
        .await?;

        Ok(())
    }

    pub async fn write_traces(
        &self,
        token: &str,
        rows: Vec<KafkaTraceRow>,
        uncompressed_bytes: u64,
        timestamps_overridden: u64,
    ) -> Result<(), WriteError> {
        if rows.is_empty() {
            return Ok(());
        }

        if timestamps_overridden > 0 {
            counter!("capture_traces_timestamps_overridden").increment(timestamps_overridden);
        }

        self.write_avro_batch(
            &self.traces_producer,
            &self.traces_topic,
            TRACES_AVRO_SCHEMA,
            token,
            &rows,
            uncompressed_bytes,
            None,
            timestamps_overridden,
            self.traces_message_max_bytes,
        )
        .await?;

        Ok(())
    }

    pub async fn write_metrics(
        &self,
        token: &str,
        rows: Vec<KafkaMetricRow>,
        uncompressed_bytes: u64,
        timestamps_overridden: u64,
    ) -> Result<(), WriteError> {
        if rows.is_empty() {
            return Ok(());
        }

        if timestamps_overridden > 0 {
            counter!("capture_metrics_timestamps_overridden").increment(timestamps_overridden);
        }

        self.write_avro_batch(
            &self.metrics_producer,
            &self.metrics_topic,
            METRICS_AVRO_SCHEMA,
            token,
            &rows,
            uncompressed_bytes,
            None,
            timestamps_overridden,
            self.metrics_message_max_bytes,
        )
        .await?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn string_schema() -> Schema {
        Schema::parse_str(r#""string""#).unwrap()
    }

    // Varied per-row content so each row adds real bytes even after zstd, keeping
    // `full > single row` regardless of the compressor.
    fn varied_rows(count: usize) -> Vec<String> {
        (0..count)
            .map(|i| {
                (0..64)
                    .map(|j| char::from(b'a' + (((i * 31 + j * 13) % 26) as u8)))
                    .collect::<String>()
            })
            .collect()
    }

    #[test]
    fn encode_chunks_splits_batch_that_exceeds_limit() {
        let schema = string_schema();
        let rows = varied_rows(50);
        let full = encode_avro(&schema, &rows).unwrap();
        let limit = full.len() - 1;

        let mut chunks = Vec::new();
        encode_chunks(&schema, &rows, limit, &mut chunks).unwrap();

        assert!(chunks.len() >= 2);
        assert!(chunks.iter().all(|c| c.payload.len() <= limit));
        assert_eq!(
            chunks.iter().map(|c| c.row_count).sum::<usize>(),
            rows.len()
        );
    }

    #[test]
    fn encode_chunks_keeps_a_fitting_batch_whole() {
        let schema = string_schema();
        let rows = varied_rows(10);
        let full = encode_avro(&schema, &rows).unwrap();

        let mut chunks = Vec::new();
        encode_chunks(&schema, &rows, full.len(), &mut chunks).unwrap();

        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].row_count, rows.len());
    }

    #[test]
    fn encode_chunks_errors_when_a_single_row_cannot_fit() {
        let schema = string_schema();
        let rows = varied_rows(1);

        let err = encode_chunks(&schema, &rows, 1, &mut Vec::new()).unwrap_err();
        assert!(matches!(err, WriteError::MessageTooLarge));
    }

    #[test]
    fn split_share_distributes_and_preserves_total() {
        let chunk_rows = [3usize, 3, 4];
        let value = 100u64;

        let mut remaining = value;
        let mut remaining_rows: usize = chunk_rows.iter().sum();
        let mut shares = Vec::new();
        for (i, &cr) in chunk_rows.iter().enumerate() {
            let is_last = i == chunk_rows.len() - 1;
            let share = split_share(remaining, cr, remaining_rows, is_last);
            remaining -= share;
            remaining_rows -= cr;
            shares.push(share);
        }

        assert_eq!(shares, vec![30, 30, 40]);
        assert_eq!(shares.iter().sum::<u64>(), value);
        assert_eq!(remaining, 0);
    }
}
