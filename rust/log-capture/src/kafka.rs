use crate::avro_schema::AVRO_SCHEMA;
use crate::log_record::KafkaLogRow;
use anyhow::anyhow;
use apache_avro::{Codec, Schema, Writer, ZstandardSettings};
use capture::config::KafkaConfig;
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
    producer: FutureProducer<KafkaContext>,
    topic: String,
}

impl KafkaSink {
    pub async fn new(config: KafkaConfig, liveness: HealthHandle) -> anyhow::Result<KafkaSink> {
        info!("connecting to Kafka brokers at {}...", config.kafka_hosts);

        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("partitioner", "murmur2_random") // Compatibility with python-kafka
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
            .set("compression.codec", config.kafka_compression_codec)
            .set(
                "queue.buffering.max.kbytes",
                (config.kafka_producer_queue_mib * 1024).to_string(),
            )
            .set("acks", config.kafka_producer_acks.to_string());

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
            liveness.report_healthy().await;
            info!("connected to Kafka brokers");
        };

        Ok(KafkaSink {
            producer,
            topic: config.kafka_topic,
        })
    }

    pub fn flush(&self) -> Result<(), KafkaError> {
        // TODO: hook it up on shutdown
        self.producer.flush(Duration::new(30, 0))
    }

    pub async fn write(&self, token: &str, rows: Vec<KafkaLogRow>) -> Result<(), anyhow::Error> {
        let schema = Schema::parse_str(AVRO_SCHEMA)?;
        let mut writer = Writer::with_codec(
            &schema,
            Vec::new(),
            Codec::Zstandard(ZstandardSettings::default()),
        );

        for row in rows {
            writer.append_ser(row)?;
        }

        let payload: Vec<u8> = writer.into_inner()?;

        let future = match self.producer.send_result(FutureRecord {
            topic: self.topic.as_str(),
            payload: Some(&payload),
            partition: None,
            key: None::<Vec<u8>>.as_ref(),
            timestamp: None,
            headers: Some(OwnedHeaders::new().insert(Header {
                key: "token",
                value: Some(&token.to_string()),
            })),
        }) {
            Err((err, _)) => Err(anyhow!(format!("kafka error: {}", err))),
            Ok(delivery_future) => Ok(delivery_future),
        }?;

        drop(future.await?);

        Ok(())
    }
}
