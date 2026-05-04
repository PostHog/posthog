use crate::avro_schema::AVRO_SCHEMA;
use crate::log_record::KafkaLogRow;
use crate::trace_record::KafkaTraceRow;
use crate::traces_avro_schema::TRACES_AVRO_SCHEMA;
use anyhow::anyhow;
use apache_avro::{Codec, Schema, Writer, ZstandardSettings};
use capture::config::KafkaConfig;
use chrono::Utc;
use health::HealthHandle;
use metrics::{counter, gauge};
use rdkafka::error::KafkaError;
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use std::result::Result::Ok;
use std::time::Duration;
use tracing::log::{debug, info};

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
    logs_topic: String,
    traces_topic: String,
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

        Ok(KafkaSink {
            logs_producer,
            traces_producer,
            logs_topic: config.kafka_topic,
            traces_topic: config.kafka_traces_topic,
        })
    }

    pub fn flush(&self) -> Result<(), KafkaError> {
        // TODO: hook it up on shutdown
        self.logs_producer.flush(Duration::new(30, 0))?;
        self.traces_producer.flush(Duration::new(30, 0))
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
        timestamps_overridden: u64,
    ) -> Result<(), anyhow::Error> {
        let schema = Schema::parse_str(avro_schema_str)?;
        let mut writer = Writer::with_codec(
            &schema,
            Vec::new(),
            Codec::Zstandard(ZstandardSettings::new(1)),
        );

        for row in rows {
            writer.append_ser(row)?;
        }

        let payload: Vec<u8> = writer.into_inner()?;

        let future = match producer.send_result(FutureRecord {
            topic,
            payload: Some(&payload),
            partition: None,
            key: None::<Vec<u8>>.as_ref(),
            timestamp: None,
            headers: Some({
                let created_at = Utc::now().to_rfc3339();
                OwnedHeaders::new()
                    .insert(Header {
                        key: "token",
                        value: Some(&token.to_string()),
                    })
                    .insert(Header {
                        key: "bytes_uncompressed",
                        value: Some(&uncompressed_bytes.to_string()),
                    })
                    .insert(Header {
                        key: "bytes_compressed",
                        value: Some(&payload.len().to_string()),
                    })
                    .insert(Header {
                        key: "record_count",
                        value: Some(&rows.len().to_string()),
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
            Err((err, _)) => Err(anyhow!(format!("kafka error: {err}"))),
            Ok(delivery_future) => Ok(delivery_future),
        }?;

        drop(future.await?);

        Ok(())
    }

    pub async fn write(
        &self,
        token: &str,
        rows: Vec<KafkaLogRow>,
        uncompressed_bytes: u64,
        timestamps_overridden: u64,
    ) -> Result<(), anyhow::Error> {
        if rows.is_empty() {
            return Ok(());
        }

        if timestamps_overridden > 0 {
            counter!("capture_logs_timestamps_overridden").increment(timestamps_overridden);
        }

        self.write_avro_batch(
            &self.logs_producer,
            &self.logs_topic,
            AVRO_SCHEMA,
            token,
            &rows,
            uncompressed_bytes,
            timestamps_overridden,
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
    ) -> Result<(), anyhow::Error> {
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
            timestamps_overridden,
        )
        .await?;

        Ok(())
    }
}
