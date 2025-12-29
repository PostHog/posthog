use crate::api::CaptureError;
use crate::config::KafkaConfig;
use crate::sinks::producer::{KafkaProducer, ProduceRecord};
use crate::sinks::Event;
use crate::v0_request::{DataType, ProcessedEvent};
use async_trait::async_trait;
use health::HealthHandle;
use limiters::overflow::{OverflowLimiter, OverflowLimiterResult};
use limiters::redis::RedisLimiter;
use metrics::{counter, gauge, histogram};
use rdkafka::error::KafkaError;
use rdkafka::producer::{FutureProducer, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use std::sync::Arc;
use std::time::Duration;
use tokio::task::JoinSet;
use tracing::log::{debug, error, info};
use tracing::{info_span, instrument, Instrument};

use super::producer::RdKafkaProducer;

pub struct KafkaContext {
    liveness: HealthHandle,
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, stats: rdkafka::Statistics) {
        // Signal liveness, as the main rdkafka loop is running and calling us
        let brokers_up = stats.brokers.values().any(|broker| broker.state == "UP");
        if brokers_up {
            self.liveness.report_healthy_blocking();
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

/// Topic configuration for the Kafka sink
#[derive(Clone)]
pub struct KafkaTopicConfig {
    pub main_topic: String,
    pub overflow_topic: String,
    pub historical_topic: String,
    pub client_ingestion_warning_topic: String,
    pub exceptions_topic: String,
    pub heatmaps_topic: String,
    pub replay_overflow_topic: String,
    pub dlq_topic: String,
}

impl From<&KafkaConfig> for KafkaTopicConfig {
    fn from(config: &KafkaConfig) -> Self {
        Self {
            main_topic: config.kafka_topic.clone(),
            overflow_topic: config.kafka_overflow_topic.clone(),
            historical_topic: config.kafka_historical_topic.clone(),
            client_ingestion_warning_topic: config.kafka_client_ingestion_warning_topic.clone(),
            exceptions_topic: config.kafka_exceptions_topic.clone(),
            heatmaps_topic: config.kafka_heatmaps_topic.clone(),
            replay_overflow_topic: config.kafka_replay_overflow_topic.clone(),
            dlq_topic: config.kafka_dlq_topic.clone(),
        }
    }
}

/// Generic Kafka sink that can use any producer implementation
pub struct KafkaSinkBase<P: KafkaProducer> {
    producer: Arc<P>,
    partition: Option<OverflowLimiter>,
    topics: KafkaTopicConfig,
    replay_overflow_limiter: Option<RedisLimiter>,
}

impl<P: KafkaProducer> Clone for KafkaSinkBase<P> {
    fn clone(&self) -> Self {
        Self {
            producer: self.producer.clone(),
            partition: self.partition.clone(),
            topics: self.topics.clone(),
            replay_overflow_limiter: self.replay_overflow_limiter.clone(),
        }
    }
}

/// The default KafkaSink using rdkafka's FutureProducer
pub type KafkaSink = KafkaSinkBase<RdKafkaProducer<KafkaContext>>;

impl KafkaSink {
    pub async fn new(
        config: KafkaConfig,
        liveness: HealthHandle,
        partition: Option<OverflowLimiter>,
        replay_overflow_limiter: Option<RedisLimiter>,
    ) -> anyhow::Result<KafkaSink> {
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
            .set(
                "socket.timeout.ms",
                config.kafka_socket_timeout_ms.to_string(),
            )
            .set("compression.codec", &config.kafka_compression_codec)
            .set(
                "queue.buffering.max.kbytes",
                (config.kafka_producer_queue_mib * 1024).to_string(),
            )
            .set("acks", &config.kafka_producer_acks);

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

        let topics = KafkaTopicConfig::from(&config);
        let rd_producer = RdKafkaProducer::new(producer);

        Ok(KafkaSinkBase {
            producer: Arc::new(rd_producer),
            partition,
            topics,
            replay_overflow_limiter,
        })
    }

    pub fn flush(&self) -> Result<(), KafkaError> {
        // TODO: hook it up on shutdown
        self.producer.flush()
    }
}

impl<P: KafkaProducer> KafkaSinkBase<P> {
    /// Create a new KafkaSinkBase with a custom producer (useful for testing)
    pub fn with_producer(
        producer: P,
        topics: KafkaTopicConfig,
        partition: Option<OverflowLimiter>,
        replay_overflow_limiter: Option<RedisLimiter>,
    ) -> Self {
        Self {
            producer: Arc::new(producer),
            partition,
            topics,
            replay_overflow_limiter,
        }
    }

    async fn kafka_send(&self, event: ProcessedEvent) -> Result<P::AckFuture, CaptureError> {
        let (event, metadata) = (event.event, event.metadata);

        let payload = serde_json::to_string(&event).map_err(|e| {
            error!("failed to serialize event: {e}");
            CaptureError::NonRetryableSinkError
        })?;

        let data_type = metadata.data_type;
        let event_key = event.key();
        let session_id = metadata.session_id.clone();
        let force_overflow = metadata.force_overflow;
        let skip_person_processing = metadata.skip_person_processing;
        let redirect_to_dlq = metadata.redirect_to_dlq;

        // Use the event's to_headers() method for consistent header serialization
        let mut headers = event.to_headers();

        drop(event); // Events can be EXTREMELY memory hungry

        // Apply skip_person_processing from event restrictions
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
            (&self.topics.dlq_topic, Some(event_key.as_str()))
        } else {
            match data_type {
                DataType::AnalyticsHistorical => {
                    (&self.topics.historical_topic, Some(event_key.as_str()))
                } // We never trigger overflow on historical events
                DataType::AnalyticsMain => {
                    // Check for force_overflow from event restrictions first
                    if force_overflow {
                        counter!(
                            "capture_events_rerouted_overflow",
                            &[("reason", "event_restriction")]
                        )
                        .increment(1);
                        // Drop partition key if skip_person_processing is set
                        let key = if skip_person_processing {
                            None
                        } else {
                            Some(event_key.as_str())
                        };
                        (&self.topics.overflow_topic, key)
                    } else {
                        // TODO: deprecate capture-led overflow or move logic in handler
                        let overflow_result = match &self.partition {
                            None => OverflowLimiterResult::NotLimited,
                            Some(partition) => partition.is_limited(&event_key),
                        };

                        match overflow_result {
                            OverflowLimiterResult::ForceLimited => {
                                headers.set_force_disable_person_processing(true);
                                counter!(
                                    "capture_events_rerouted_overflow",
                                    &[("reason", "force_limited")]
                                )
                                .increment(1);
                                (&self.topics.overflow_topic, None)
                            }
                            OverflowLimiterResult::Limited => {
                                counter!(
                                    "capture_events_rerouted_overflow",
                                    &[("reason", "rate_limited")]
                                )
                                .increment(1);
                                if self.partition.as_ref().unwrap().should_preserve_locality() {
                                    (&self.topics.overflow_topic, Some(event_key.as_str()))
                                } else {
                                    (&self.topics.overflow_topic, None)
                                }
                            }
                            OverflowLimiterResult::NotLimited => {
                                // event_key is "<token>:<distinct_id>" for std events or
                                // "<token>:<ip_addr>" for cookieless events
                                (&self.topics.main_topic, Some(event_key.as_str()))
                            }
                        }
                    }
                }
                DataType::ClientIngestionWarning => (
                    &self.topics.client_ingestion_warning_topic,
                    Some(event_key.as_str()),
                ),
                DataType::HeatmapMain => (&self.topics.heatmaps_topic, Some(event_key.as_str())),
                DataType::ExceptionMain => {
                    (&self.topics.exceptions_topic, Some(event_key.as_str()))
                }
                DataType::SnapshotMain => {
                    let session_id = session_id
                        .as_deref()
                        .ok_or(CaptureError::MissingSessionId)?;

                    // Check for force_overflow from event restrictions first
                    if force_overflow {
                        counter!(
                            "capture_events_rerouted_overflow",
                            &[("reason", "event_restriction")]
                        )
                        .increment(1);
                        (&self.topics.replay_overflow_topic, Some(session_id))
                    } else {
                        let is_overflowing = match &self.replay_overflow_limiter {
                            None => false,
                            Some(limiter) => limiter.is_limited(session_id).await,
                        };

                        if is_overflowing {
                            (&self.topics.replay_overflow_topic, Some(session_id))
                        } else {
                            (&self.topics.main_topic, Some(session_id))
                        }
                    }
                }
            }
        };

        let record = ProduceRecord {
            topic: topic.to_string(),
            key: partition_key.map(|s| s.to_string()),
            payload,
            headers,
        };

        self.producer.send(record)
    }
}

#[async_trait]
impl<P: KafkaProducer + 'static> Event for KafkaSinkBase<P> {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let ack_future = self.kafka_send(event).await?;
        histogram!("capture_event_batch_size").record(1.0);
        ack_future.instrument(info_span!("ack_wait_one")).await
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let mut set = JoinSet::new();
        let batch_size = events.len();
        for event in events {
            // We await kafka_send to get events in the producer queue sequentially
            let ack_future = self.kafka_send(event).await?;

            // Then stash the returned future, waiting concurrently for the write ACKs from brokers.
            set.spawn(ack_future);
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
                        error!("join error while waiting on Kafka ACK: {err:?}");
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
    use crate::api::CaptureError;
    use crate::config;
    use crate::sinks::kafka::KafkaSink;
    use crate::sinks::Event;
    use crate::utils::uuid_v7;
    use crate::v0_request::{DataType, ProcessedEvent, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use health::HealthRegistry;
    use limiters::overflow::OverflowLimiter;
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
            false,
        ));
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
            kafka_exceptions_topic: "events_plugin_ingestion".to_string(),
            kafka_heatmaps_topic: "events_plugin_ingestion".to_string(),
            kafka_replay_overflow_topic: "session_recording_snapshot_item_overflow".to_string(),
            kafka_dlq_topic: "events_plugin_ingestion_dlq".to_string(),
            kafka_tls: false,
            kafka_client_id: "".to_string(),
            kafka_metadata_max_age_ms: 60000,
            kafka_producer_max_retries: 2,
            kafka_producer_acks: "all".to_string(),
            kafka_socket_timeout_ms: 60000,
        };
        let sink = KafkaSink::new(config, handle, limiter, None)
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
        };

        // Convert to owned headers and back
        let owned_headers: OwnedHeaders = headers.into();
        let parsed_headers = CapturedEventHeaders::from(owned_headers);

        // Verify the 'now' field is preserved
        assert_eq!(parsed_headers.now, Some(test_now));
        assert_eq!(parsed_headers.token, Some("test_token".to_string()));
        assert_eq!(parsed_headers.distinct_id, Some("test_id".to_string()));
    }

    #[cfg(test)]
    mod topic_routing {
        use super::*;
        use crate::sinks::kafka::{KafkaSinkBase, KafkaTopicConfig};
        use crate::sinks::producer::MockKafkaProducer;

        const MAIN_TOPIC: &str = "events_plugin_ingestion";
        const OVERFLOW_TOPIC: &str = "events_plugin_ingestion_overflow";
        const DLQ_TOPIC: &str = "events_plugin_ingestion_dlq";
        const HISTORICAL_TOPIC: &str = "events_plugin_ingestion_historical";
        const HEATMAPS_TOPIC: &str = "heatmaps";
        const EXCEPTIONS_TOPIC: &str = "exceptions";
        const CLIENT_INGESTION_WARNING_TOPIC: &str = "client_ingestion_warning";
        const REPLAY_OVERFLOW_TOPIC: &str = "replay_overflow";

        fn create_test_topics() -> KafkaTopicConfig {
            KafkaTopicConfig {
                main_topic: MAIN_TOPIC.to_string(),
                overflow_topic: OVERFLOW_TOPIC.to_string(),
                historical_topic: HISTORICAL_TOPIC.to_string(),
                client_ingestion_warning_topic: CLIENT_INGESTION_WARNING_TOPIC.to_string(),
                exceptions_topic: EXCEPTIONS_TOPIC.to_string(),
                heatmaps_topic: HEATMAPS_TOPIC.to_string(),
                replay_overflow_topic: REPLAY_OVERFLOW_TOPIC.to_string(),
                dlq_topic: DLQ_TOPIC.to_string(),
            }
        }

        fn create_test_event(
            data_type: DataType,
            force_overflow: bool,
            skip_person_processing: bool,
            redirect_to_dlq: bool,
        ) -> ProcessedEvent {
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
                data_type,
                session_id: Some("session123".to_string()),
                computed_timestamp: None,
                event_name: "test_event".to_string(),
                force_overflow,
                skip_person_processing,
                redirect_to_dlq,
            };

            ProcessedEvent { event, metadata }
        }

        struct ExpectedRouting<'a> {
            topic: &'a str,
            has_key: bool,
            force_disable_person_processing: Option<bool>,
        }

        async fn assert_routing(
            data_type: DataType,
            force_overflow: bool,
            skip_person_processing: bool,
            redirect_to_dlq: bool,
            expected: ExpectedRouting<'_>,
        ) {
            let producer = MockKafkaProducer::new();
            let sink =
                KafkaSinkBase::with_producer(producer.clone(), create_test_topics(), None, None);

            let event = create_test_event(
                data_type,
                force_overflow,
                skip_person_processing,
                redirect_to_dlq,
            );
            sink.send(event).await.unwrap();

            let records = producer.get_records();
            assert_eq!(records.len(), 1, "Expected exactly one record");
            assert_eq!(
                records[0].topic, expected.topic,
                "Wrong topic for {data_type:?} (overflow={force_overflow}, skip_person={skip_person_processing}, dlq={redirect_to_dlq})"
            );
            assert_eq!(
                records[0].key.is_some(),
                expected.has_key,
                "Wrong key presence for {data_type:?} (overflow={force_overflow}, skip_person={skip_person_processing}, dlq={redirect_to_dlq})"
            );
            assert_eq!(
                records[0].headers.force_disable_person_processing,
                expected.force_disable_person_processing,
                "Wrong header for {data_type:?} (overflow={force_overflow}, skip_person={skip_person_processing}, dlq={redirect_to_dlq})"
            );
        }

        // ==================== AnalyticsMain ====================

        #[tokio::test]
        async fn analytics_main_normal() {
            assert_routing(
                DataType::AnalyticsMain,
                false,
                false,
                false,
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
                DataType::AnalyticsMain,
                true,
                false,
                false,
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
                DataType::AnalyticsMain,
                true,
                true,
                false,
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
            assert_routing(
                DataType::AnalyticsMain,
                false,
                true,
                false,
                ExpectedRouting {
                    topic: MAIN_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                },
            )
            .await;
        }

        #[tokio::test]
        async fn analytics_main_redirect_to_dlq() {
            assert_routing(
                DataType::AnalyticsMain,
                false,
                false,
                true,
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
                DataType::AnalyticsMain,
                true,
                false,
                true,
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
                DataType::AnalyticsMain,
                false,
                true,
                true,
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
                DataType::AnalyticsMain,
                true,
                true,
                true,
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
                DataType::AnalyticsHistorical,
                false,
                false,
                false,
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
                DataType::AnalyticsHistorical,
                true,
                false,
                false,
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
                DataType::AnalyticsHistorical,
                false,
                true,
                false,
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
                DataType::AnalyticsHistorical,
                false,
                false,
                true,
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
                DataType::AnalyticsHistorical,
                true,
                true,
                true,
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
                DataType::SnapshotMain,
                false,
                false,
                false,
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
                DataType::SnapshotMain,
                true,
                false,
                false,
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
                DataType::SnapshotMain,
                true,
                true,
                false,
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
                DataType::SnapshotMain,
                false,
                true,
                false,
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
                DataType::SnapshotMain,
                false,
                false,
                true,
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
                DataType::SnapshotMain,
                true,
                false,
                true,
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
                DataType::HeatmapMain,
                false,
                false,
                false,
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
                DataType::HeatmapMain,
                true,
                false,
                false,
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
                DataType::HeatmapMain,
                false,
                true,
                false,
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
                DataType::HeatmapMain,
                false,
                false,
                true,
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                },
            )
            .await;
        }

        // ==================== ExceptionMain ====================
        // Exceptions IGNORE force_overflow

        #[tokio::test]
        async fn exception_normal() {
            assert_routing(
                DataType::ExceptionMain,
                false,
                false,
                false,
                ExpectedRouting {
                    topic: EXCEPTIONS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_ignores_force_overflow() {
            assert_routing(
                DataType::ExceptionMain,
                true,
                false,
                false,
                ExpectedRouting {
                    topic: EXCEPTIONS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_skip_person() {
            assert_routing(
                DataType::ExceptionMain,
                false,
                true,
                false,
                ExpectedRouting {
                    topic: EXCEPTIONS_TOPIC,
                    has_key: true,
                    force_disable_person_processing: Some(true),
                },
            )
            .await;
        }

        #[tokio::test]
        async fn exception_redirect_to_dlq() {
            assert_routing(
                DataType::ExceptionMain,
                false,
                false,
                true,
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
                DataType::ClientIngestionWarning,
                false,
                false,
                false,
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
                DataType::ClientIngestionWarning,
                true,
                false,
                false,
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
                DataType::ClientIngestionWarning,
                false,
                true,
                false,
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
                DataType::ClientIngestionWarning,
                false,
                false,
                true,
                ExpectedRouting {
                    topic: DLQ_TOPIC,
                    has_key: true,
                    force_disable_person_processing: None,
                },
            )
            .await;
        }
    }
}
