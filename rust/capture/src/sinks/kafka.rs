use std::time::Duration;

use async_trait::async_trait;
use health::HealthHandle;
use metrics::{counter, gauge, histogram};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use tokio::task::JoinSet;
use tracing::log::{debug, error, info};
use tracing::{info_span, instrument, Instrument};

use crate::api::{CaptureError, DataType, ProcessedEvent};
use crate::config::KafkaConfig;
use crate::limiters::overflow::OverflowLimiter;
use crate::prometheus::report_dropped_events;
use crate::sinks::Event;

struct KafkaContext {
    liveness: HealthHandle,
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, stats: rdkafka::Statistics) {
        // Signal liveness, as the main rdkafka loop is running and calling us
        self.liveness.report_healthy_blocking();

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
    partition: Option<OverflowLimiter>,
    main_topic: String,
    historical_topic: String,
    client_ingestion_warning_topic: String,
    exceptions_topic: String,
    heatmaps_topic: String,
}

impl KafkaSink {
    pub fn new(
        config: KafkaConfig,
        liveness: HealthHandle,
        partition: Option<OverflowLimiter>,
    ) -> anyhow::Result<KafkaSink> {
        info!("connecting to Kafka brokers at {}...", config.kafka_hosts);

        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("partitioner", "murmur2_random") // Compatibility with python-kafka
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
            );

        if !&config.kafka_client_id.is_empty() {
            client_config.set("client.id", &config.kafka_client_id);
        }

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        debug!("rdkafka configuration: {:?}", client_config);
        let producer: FutureProducer<KafkaContext> =
            client_config.create_with_context(KafkaContext { liveness })?;

        // Ping the cluster to make sure we can reach brokers, fail after 10 seconds
        drop(producer.client().fetch_metadata(
            Some("__consumer_offsets"),
            Timeout::After(Duration::new(10, 0)),
        )?);
        info!("connected to Kafka brokers");

        Ok(KafkaSink {
            producer,
            partition,
            main_topic: config.kafka_topic,
            historical_topic: config.kafka_historical_topic,
            client_ingestion_warning_topic: config.kafka_client_ingestion_warning_topic,
            exceptions_topic: config.kafka_exceptions_topic,
            heatmaps_topic: config.kafka_heatmaps_topic,
        })
    }

    pub fn flush(&self) -> Result<(), KafkaError> {
        // TODO: hook it up on shutdown
        self.producer.flush(Duration::new(30, 0))
    }

    async fn kafka_send(&self, event: ProcessedEvent) -> Result<DeliveryFuture, CaptureError> {
        let payload = serde_json::to_string(&event).map_err(|e| {
            error!("failed to serialize event: {}", e);
            CaptureError::NonRetryableSinkError
        })?;

        let event_key = event.key();
        let session_id = event.session_id.as_deref();

        let (topic, partition_key): (&str, Option<&str>) = match &event.data_type {
            DataType::AnalyticsHistorical => (&self.historical_topic, Some(event_key.as_str())), // We never trigger overflow on historical events
            DataType::AnalyticsMain => {
                // TODO: deprecate capture-led overflow or move logic in handler
                let is_limited = match &self.partition {
                    None => false,
                    Some(partition) => partition.is_limited(&event_key),
                };
                if is_limited {
                    (&self.main_topic, None) // Analytics overflow goes to the main topic without locality
                } else {
                    (&self.main_topic, Some(event_key.as_str()))
                }
            }
            DataType::ClientIngestionWarning => (
                &self.client_ingestion_warning_topic,
                Some(event_key.as_str()),
            ),
            DataType::HeatmapMain => (&self.heatmaps_topic, Some(event_key.as_str())),
            DataType::ExceptionMain => (&self.exceptions_topic, Some(event_key.as_str())),
            DataType::SnapshotMain => (
                &self.main_topic,
                Some(session_id.ok_or(CaptureError::MissingSessionId)?),
            ),
        };

        match self.producer.send_result(FutureRecord {
            topic,
            payload: Some(&payload),
            partition: None,
            key: partition_key,
            timestamp: None,
            headers: Some(OwnedHeaders::new().insert(Header {
                key: "token",
                value: Some(&event.token),
            })),
        }) {
            Ok(ack) => Ok(ack),
            Err((e, _)) => match e.rdkafka_error_code() {
                Some(RDKafkaErrorCode::MessageSizeTooLarge) => {
                    report_dropped_events("kafka_message_size", 1);
                    Err(CaptureError::EventTooBig)
                }
                _ => {
                    // TODO(maybe someday): Don't drop them but write them somewhere and try again
                    report_dropped_events("kafka_write_error", 1);
                    error!("failed to produce event: {}", e);
                    Err(CaptureError::RetryableSinkError)
                }
            },
        }
    }

    async fn process_ack(delivery: DeliveryFuture) -> Result<(), CaptureError> {
        match delivery.await {
            Err(_) => {
                // Cancelled due to timeout while retrying
                counter!("capture_kafka_produce_errors_total").increment(1);
                error!("failed to produce to Kafka before write timeout");
                Err(CaptureError::RetryableSinkError)
            }
            Ok(Err((KafkaError::MessageProduction(RDKafkaErrorCode::MessageSizeTooLarge), _))) => {
                // Rejected by broker due to message size
                report_dropped_events("kafka_message_size", 1);
                Err(CaptureError::EventTooBig)
            }
            Ok(Err((err, _))) => {
                // Unretriable produce error
                counter!("capture_kafka_produce_errors_total").increment(1);
                error!("failed to produce to Kafka: {}", err);
                Err(CaptureError::RetryableSinkError)
            }
            Ok(Ok(_)) => {
                counter!("capture_events_ingested_total").increment(1);
                Ok(())
            }
        }
    }
}

#[async_trait]
impl Event for KafkaSink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let ack = self.kafka_send(event).await?;
        histogram!("capture_event_batch_size").record(1.0);
        Self::process_ack(ack)
            .instrument(info_span!("ack_wait_one"))
            .await
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let mut set = JoinSet::new();
        let batch_size = events.len();
        for event in events {
            // We await kafka_send to get events in the producer queue sequentially
            let ack = self.kafka_send(event).await?;

            // Then stash the returned DeliveryFuture, waiting concurrently for the write ACKs from brokers.
            set.spawn(Self::process_ack(ack));
        }

        // Await on all the produce promises, fail batch on first failure
        async move {
            while let Some(res) = set.join_next().await {
                match res {
                    Ok(Ok(_)) => {}
                    Ok(Err(err)) => {
                        set.abort_all();
                        return Err(err);
                    }
                    Err(err) => {
                        set.abort_all();
                        error!("join error while waiting on Kafka ACK: {:?}", err);
                        return Err(CaptureError::RetryableSinkError);
                    }
                }
            }
            Ok(())
        }
        .instrument(info_span!("ack_wait_many"))
        .await?;

        histogram!("capture_event_batch_size").record(batch_size as f64);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use crate::api::{CaptureError, DataType, ProcessedEvent};
    use crate::config;
    use crate::limiters::overflow::OverflowLimiter;
    use crate::sinks::kafka::KafkaSink;
    use crate::sinks::Event;
    use crate::utils::uuid_v7;
    use health::HealthRegistry;
    use rand::distributions::Alphanumeric;
    use rand::Rng;
    use rdkafka::mocking::MockCluster;
    use rdkafka::producer::DefaultProducerContext;
    use rdkafka::types::{RDKafkaApiKey, RDKafkaRespErr};
    use std::num::NonZeroU32;
    use time::Duration;

    async fn start_on_mocked_sink(
        message_max_bytes: Option<u32>,
    ) -> (MockCluster<'static, DefaultProducerContext>, KafkaSink) {
        let registry = HealthRegistry::new("liveness");
        let handle = registry
            .register("one".to_string(), Duration::seconds(30))
            .await;
        let limiter = Some(OverflowLimiter::new(
            NonZeroU32::new(10).unwrap(),
            NonZeroU32::new(10).unwrap(),
            None,
        ));
        let cluster = MockCluster::new(1).expect("failed to create mock brokers");
        let config = config::KafkaConfig {
            kafka_producer_linger_ms: 0,
            kafka_producer_queue_mib: 50,
            kafka_message_timeout_ms: 500,
            kafka_producer_message_max_bytes: message_max_bytes.unwrap_or(1000000),
            kafka_compression_codec: "none".to_string(),
            kafka_hosts: cluster.bootstrap_servers(),
            kafka_topic: "events_plugin_ingestion".to_string(),
            kafka_historical_topic: "events_plugin_ingestion_historical".to_string(),
            kafka_client_ingestion_warning_topic: "events_plugin_ingestion".to_string(),
            kafka_exceptions_topic: "events_plugin_ingestion".to_string(),
            kafka_heatmaps_topic: "events_plugin_ingestion".to_string(),
            kafka_tls: false,
        };
        let sink = KafkaSink::new(config, handle, limiter).expect("failed to create sink");
        (cluster, sink)
    }

    #[tokio::test]
    async fn kafka_sink_error_handling() {
        // Uses a mocked Kafka broker that allows injecting write errors, to check error handling.
        // We test different cases in a single test to amortize the startup cost of the producer.

        let (cluster, sink) = start_on_mocked_sink(Some(3000000)).await;
        let event: ProcessedEvent = ProcessedEvent {
            data_type: DataType::AnalyticsMain,
            uuid: uuid_v7(),
            distinct_id: "id1".to_string(),
            ip: "".to_string(),
            data: "".to_string(),
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            session_id: None,
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
        let big_event: ProcessedEvent = ProcessedEvent {
            data_type: DataType::AnalyticsMain,
            uuid: uuid_v7(),
            distinct_id: "id1".to_string(),
            ip: "".to_string(),
            data: big_data,
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            session_id: None,
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
        let big_event: ProcessedEvent = ProcessedEvent {
            data_type: DataType::AnalyticsMain,
            uuid: uuid_v7(),
            distinct_id: "id1".to_string(),
            ip: "".to_string(),
            data: big_data,
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
            session_id: None,
        };
        match sink.send(big_event).await {
            Err(CaptureError::EventTooBig) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };

        // Simulate unretriable errors
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_MSG_SIZE_TOO_LARGE; 1];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send(event.clone()).await {
            Err(CaptureError::EventTooBig) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_INVALID_PARTITIONS; 1];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send_batch(vec![event.clone(), event.clone()]).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
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
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };
        match sink.send_batch(vec![event.clone(), event.clone()]).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };
    }
}
