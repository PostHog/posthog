use anyhow::{Context, Result};
use common_kafka::{
    config::KafkaConfig,
    kafka_producer::{create_kafka_producer, KafkaContext},
};
use health::HealthRegistry;
use rdkafka::{
    consumer::{Consumer, StreamConsumer},
    error::{KafkaError, RDKafkaErrorCode},
    message::{BorrowedHeaders, BorrowedMessage},
    producer::{FutureRecord, Producer},
    ClientConfig, Message,
};
use std::time::Duration;
use tokio::time::sleep;
use tracing::{error, info, warn};

use crate::config::Config;
use crate::repartitioners::compute_propdefs_v1_key_by_team_id;

const KAFKA_CONSUMER_ERROR: &str = "kafka_consumer_error";
const KAFKA_PRODUCER_ERROR: &str = "kafka_producer_error";
const KAFKA_MESSAGE_CONSUMED: &str = "kafka_message_consumed";
const KAFKA_MESSAGE_PROCESSED: &str = "kafka_message_processed";
const KAFKA_MESSAGE_PRODUCED: &str = "kafka_message_produced";
const REPARTITIONER_PROCESSING_ERROR: &str = "repartitioner_processing_error";
pub struct RepartitionerService {
    config: Config,
    consumer: StreamConsumer,
    producer: rdkafka::producer::FutureProducer<KafkaContext>,
    health: HealthRegistry,
}

impl RepartitionerService {
    pub async fn new(config: Config, health: HealthRegistry) -> Result<Self> {
        let kafka_config = KafkaConfig {
            kafka_hosts: config.kafka_hosts.clone(),
            kafka_tls: config.kafka_tls,
            kafka_producer_linger_ms: config.kafka_producer_linger_ms,
            kafka_producer_queue_mib: config.kafka_producer_queue_mib,
            kafka_producer_queue_messages: config.kafka_producer_queue_messages,
            kafka_message_timeout_ms: config.kafka_message_timeout_ms,
            kafka_compression_codec: config.kafka_compression_codec.clone(),
        };

        // Create consumer directly to get raw messages
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("group.id", &config.kafka_consumer_group)
            .set("auto.offset.reset", &config.kafka_consumer_offset_reset)
            .set("enable.auto.offset.store", "false"); // service controls when we advance offsets, even with autocommit enabled

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }

        if config.kafka_consumer_auto_commit {
            client_config.set("enable.auto.commit", "true").set(
                "auto.commit.interval.ms",
                config.kafka_consumer_auto_commit_interval_ms.to_string(),
            );
        }

        let consumer: StreamConsumer = client_config
            .create()
            .context("Failed to create Kafka consumer")?;
        consumer
            .subscribe(&[&config.kafka_source_topic])
            .context("Failed to subscribe to topic")?;

        let health_handle = health
            .register("kafka_producer".to_string(), Duration::from_secs(30))
            .await;
        let producer = create_kafka_producer(&kafka_config, health_handle)
            .await
            .context("Failed to create Kafka producer")?;

        info!(
            "Repartitioner service initialized: consuming from '{}', producing to '{}'",
            config.kafka_source_topic, config.kafka_destination_topic
        );

        Ok(Self {
            config,
            consumer,
            producer,
            health,
        })
    }

    pub async fn run(&self) -> Result<()> {
        info!("Starting repartitioner service");
        let mut kafka_error_count = 0;

        let consumer_health = self
            .health
            .register("kafka_consumer".to_string(), Duration::from_secs(30))
            .await;
        consumer_health.report_healthy().await;

        loop {
            // Update health check at start of loop iteration (like cymbal)
            consumer_health.report_healthy().await;

            match self.consumer.recv().await {
                Ok(message) => {
                    metrics::counter!(KAFKA_MESSAGE_CONSUMED).increment(1);

                    if let Err(e) = self.process_message(&message).await {
                        // Processing error mean we can't obtain the new partition key.
                        // this should be exceedingly rare, but if it happens, we have
                        // no choice but to drop the message and continue
                        error!("Failed to process message, dropping it: {}", e);
                        metrics::counter!(REPARTITIONER_PROCESSING_ERROR).increment(1);
                    } else {
                        metrics::counter!(KAFKA_MESSAGE_PROCESSED).increment(1);
                    }

                    // clear error count and store offset best-effort
                    kafka_error_count = 0;
                    let _ignored = self.consumer.store_offset(
                        message.topic(),
                        message.partition(),
                        message.offset() + 1,
                    );
                }
                Err(e) => {
                    kafka_error_count += 1;
                    if let Some(e) = self.handle_kafka_error(e, kafka_error_count).await {
                        if e == KafkaError::Canceled {
                            self.shutdown().await;
                            return Ok(());
                        }

                        consumer_health
                            .report_status(health::ComponentStatus::Unhealthy)
                            .await;
                        self.shutdown().await;
                        return Err(anyhow::anyhow!(
                            "FATAL Kafka error - terminating pod: {}",
                            e
                        ));
                    }
                }
            }
        }
    }

    fn flush_producer(&self) {
        match self.producer.flush(Duration::from_secs(
            self.config.kafka_producer_graceful_shutdown_secs,
        )) {
            Ok(_) => (),

            Err(e) => {
                warn!("Failed to flush producer on graceful shutdown: {e:?}");
                metrics::counter!(
                    KAFKA_PRODUCER_ERROR,
                    &[("level", "warn"), ("error", "flush_producer"),]
                )
                .increment(1);
            }
        }
    }

    async fn handle_kafka_error(&self, e: KafkaError, current_count: u64) -> Option<KafkaError> {
        match &e {
            KafkaError::MessageConsumption(code) => {
                match code {
                    RDKafkaErrorCode::PartitionEOF => {
                        metrics::counter!(
                            KAFKA_CONSUMER_ERROR,
                            &[("level", "info"), ("error", "partition_eof"),]
                        )
                        .increment(1);
                    }
                    RDKafkaErrorCode::OperationTimedOut => {
                        metrics::counter!(
                            KAFKA_CONSUMER_ERROR,
                            &[("level", "info"), ("error", "op_timed_out"),]
                        )
                        .increment(1);
                    }
                    RDKafkaErrorCode::OffsetOutOfRange => {
                        // "auto.offset.reset" will trigger a seek to head or tail
                        // of the partition in coordination with the broker
                        warn!(
                            "Offset out of range - seeking to {}",
                            self.config.kafka_consumer_offset_reset
                        );
                        metrics::counter!(
                            KAFKA_CONSUMER_ERROR,
                            &[("level", "info"), ("error", "offset_out_of_range"),]
                        )
                        .increment(1);
                        sleep(Duration::from_millis(500)).await;
                    }
                    _ => {
                        warn!("Kafka consumer error: {code:?}");
                        metrics::counter!(
                            KAFKA_CONSUMER_ERROR,
                            &[("level", "warn"), ("error", "consumer"),]
                        )
                        .increment(1);
                        sleep(Duration::from_millis(100 * current_count.min(10))).await;
                    }
                }

                None
            }

            KafkaError::MessageConsumptionFatal(code) => {
                error!("Fatal Kafka consumer error: {code:?}");
                metrics::counter!(
                    KAFKA_CONSUMER_ERROR,
                    &[("level", "fatal"), ("error", "consumer"),]
                )
                .increment(1);

                Some(e)
            }

            // Connection issues
            KafkaError::Global(code) => {
                match code {
                    RDKafkaErrorCode::AllBrokersDown => {
                        warn!("All brokers down: {code:?} - waiting for reconnect");
                        metrics::counter!(
                            KAFKA_CONSUMER_ERROR,
                            &[("level", "warn"), ("error", "all_brokers_down"),]
                        )
                        .increment(1);
                        sleep(Duration::from_secs(current_count.min(5))).await;
                    }
                    RDKafkaErrorCode::BrokerTransportFailure => {
                        warn!("Broker transport failure: {code:?} - waiting for reconnect");
                        metrics::counter!(
                            KAFKA_CONSUMER_ERROR,
                            &[("level", "warn"), ("error", "broker_transport"),]
                        )
                        .increment(1);
                        sleep(Duration::from_secs(current_count.min(3))).await;
                    }
                    RDKafkaErrorCode::Authentication => {
                        error!("Authentication failed: {code:?}");
                        metrics::counter!(
                            KAFKA_CONSUMER_ERROR,
                            &[("level", "fatal"), ("error", "authentication"),]
                        )
                        .increment(1);
                        return Some(e);
                    }
                    _ => {
                        warn!("Global Kafka error: {code:?}");
                        metrics::counter!(
                            KAFKA_CONSUMER_ERROR,
                            &[("level", "warn"), ("error", "global"),]
                        )
                        .increment(1);
                        sleep(Duration::from_millis(500 * current_count.min(6))).await;
                    }
                }

                None
            }

            // Shutdown signal
            KafkaError::Canceled => {
                info!("Consumer canceled - shutting down");
                metrics::counter!(
                    KAFKA_CONSUMER_ERROR,
                    &[("level", "info"), ("error", "canceled"),]
                )
                .increment(1);

                Some(e)
            }

            // Other errors
            _ => {
                error!("Unexpected error: {:?}", e);
                metrics::counter!(
                    KAFKA_CONSUMER_ERROR,
                    &[("level", "fatal"), ("error", "unexpected"),]
                )
                .increment(1);
                sleep(Duration::from_millis(100 * current_count.min(10))).await;

                None
            }
        }
    }

    async fn shutdown(&self) {
        info!(
            "Graceful shutdown: unsubscribing from source topic {}...",
            self.config.kafka_source_topic
        );
        self.consumer.unsubscribe();
        info!(
            "Graceful shutdown: flushing producer to dest topic {}...",
            self.config.kafka_destination_topic
        );
        self.flush_producer();
        info!("Graceful shutdown: completed");
    }

    async fn process_message(&self, message: &BorrowedMessage<'_>) -> Result<()> {
        let payload = message.payload();
        let headers = message.headers();
        let key = message.key();

        // Compute new partition key (example: using a hash of the payload)
        // You can customize this logic based on your requirements
        let new_key = match self.compute_partition_key(key, headers, payload) {
            Ok(key) => key,
            Err(e) => {
                error!("Failed to compute partition key: {}", e);
                return Err(e);
            }
        };

        // Build record with new partition key, using borrowed payload
        // Headers are converted from BorrowedHeaders to OwnedHeaders only when needed
        // (FutureRecord requires OwnedHeaders due to async send semantics)
        let owned_headers = message.headers().map(|h| h.detach());

        let record = FutureRecord {
            topic: &self.config.kafka_destination_topic,
            partition: None, // producer will hash the message key to assign a destination partition
            key: Some(&new_key),
            payload,
            timestamp: message.timestamp().to_millis(),
            headers: owned_headers,
        };

        // Send to Kafka
        let future = self
            .producer
            .send_result(record)
            .map_err(|(e, _)| anyhow::anyhow!("Failed to queue message: {:?}", e))
            .context("Failed to send message to output topic")?;

        match future.await {
            Ok(Ok(_)) => {
                metrics::counter!(KAFKA_MESSAGE_PRODUCED).increment(1);
                Ok(())
            }
            Ok(Err((e, _))) => {
                metrics::counter!(
                    KAFKA_PRODUCER_ERROR,
                    &[("level", "error"), ("error", "send_failed"),]
                )
                .increment(1);
                Err(anyhow::anyhow!("Failed to send: {:?}", e))
                    .context("Failed to send message to output topic")
            }
            Err(_) => {
                metrics::counter!(
                    KAFKA_PRODUCER_ERROR,
                    &[("level", "warn"), ("error", "send_future_canceled"),]
                )
                .increment(1);
                Err(anyhow::anyhow!("Send future was canceled"))
                    .context("Failed to send message to output topic")
            }
        }
    }

    /// match the repartitioning function to the value in the deploy env config
    fn compute_partition_key(
        &self,
        source_key: Option<&[u8]>,
        headers: Option<&BorrowedHeaders>,
        payload: Option<&[u8]>,
    ) -> Result<Vec<u8>> {
        match self.config.partition_key_compute_fn.as_str() {
            "propdefs_v1_by_team_id" => {
                compute_propdefs_v1_key_by_team_id(source_key, headers, payload)
            }

            // TODO: map more repartitioning functions here as needed
            _ => {
                metrics::counter!(
                    REPARTITIONER_PROCESSING_ERROR,
                    &[("level", "fatal"), ("error", "unknown_partition_key_fn"),]
                )
                .increment(1);
                Err(anyhow::anyhow!(
                    "Unknown partition key compute function: {}",
                    self.config.partition_key_compute_fn
                ))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use common_kafka::test::create_mock_kafka;
    use rdkafka::{
        client::DefaultClientContext,
        consumer::Consumer,
        producer::{FutureProducer, FutureRecord},
        util::Timeout,
    };
    use serde_json::json;
    use std::time::Duration;
    use tokio::time::timeout;
    use uuid::Uuid;

    async fn setup_test_environment() -> (
        rdkafka::mocking::MockCluster<'static, rdkafka::producer::DefaultProducerContext>,
        StreamConsumer,
        FutureProducer<DefaultClientContext>,
        String,
        String,
    ) {
        let (cluster, _) = create_mock_kafka().await;
        let bootstrap_servers = cluster.bootstrap_servers();

        let source_topic = format!("test_source_{}", Uuid::new_v4());
        let dest_topic = format!("test_dest_{}", Uuid::new_v4());

        let producer: FutureProducer<DefaultClientContext> = ClientConfig::new()
            .set("bootstrap.servers", &bootstrap_servers)
            .set("metadata.max.age.ms", "1000")
            .create()
            .expect("Failed to create producer");

        let consumer: StreamConsumer = ClientConfig::new()
            .set("bootstrap.servers", &bootstrap_servers)
            .set("group.id", format!("test_group_{}", Uuid::new_v4()))
            .set("auto.offset.reset", "earliest")
            .set("enable.auto.commit", "false")
            .set("metadata.max.age.ms", "1000")
            .set("session.timeout.ms", "3000")
            .set("heartbeat.interval.ms", "500")
            .set("max.poll.interval.ms", "5000")
            .create()
            .expect("Failed to create consumer");

        tokio::time::sleep(Duration::from_millis(100)).await;

        (cluster, consumer, producer, source_topic, dest_topic)
    }

    fn create_test_message(event_name: &str, distinct_id: &str, team_id: i64) -> Vec<u8> {
        let payload = json!({
            "event": event_name,
            "distinct_id": distinct_id,
            "team_id": team_id,
            "project_id": team_id,
            "timestamp": Utc::now().to_rfc3339(),
            "created_at": Utc::now().to_rfc3339(),
            "properties": {},
            "person_mode": "full",
            "person_id": Uuid::new_v4().to_string(),
            "person_properties": {},
            "person_created_at": Utc::now().to_rfc3339(),
            "elements_chain": "",
        });
        serde_json::to_vec(&payload).expect("Failed to serialize test message")
    }

    async fn produce_test_message(
        producer: &FutureProducer<DefaultClientContext>,
        topic: &str,
        payload: Vec<u8>,
    ) -> Result<()> {
        let record: FutureRecord<'_, [u8], [u8]> =
            FutureRecord::to(topic).payload(payload.as_slice());
        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send: {:?}", e))?;
        Ok(())
    }

    #[tokio::test]
    async fn test_mock_cluster() {
        let (_cluster, consumer, producer, source_topic, _dest_topic) =
            setup_test_environment().await;

        let event_name = "test_event";
        let distinct_id = Uuid::new_v4().to_string();
        let team_id = 123;
        let payload = create_test_message(event_name, &distinct_id, team_id);

        produce_test_message(&producer, &source_topic, payload.clone())
            .await
            .expect("Failed to produce message");

        tokio::time::sleep(Duration::from_millis(200)).await;

        consumer
            .subscribe(&[&source_topic])
            .expect("Failed to subscribe");

        let message = timeout(Duration::from_secs(5), consumer.recv())
            .await
            .expect("Timeout waiting for message")
            .expect("Failed to receive message");

        let received_payload = message.payload().expect("Message has no payload");
        let received_json: serde_json::Value =
            serde_json::from_slice(received_payload).expect("Failed to parse JSON");

        assert_eq!(received_json["event"], event_name);
        assert_eq!(received_json["distinct_id"], distinct_id);
        assert_eq!(received_json["team_id"].as_i64(), Some(team_id));
        assert_eq!(received_json["project_id"].as_i64(), Some(team_id));
        assert_eq!(received_json["person_mode"], "full");
        assert_eq!(received_json["elements_chain"], "");
    }

    #[tokio::test]
    async fn test_service_with_single_event() {
        let (cluster, consumer, producer, source_topic, dest_topic) =
            setup_test_environment().await;

        let event_name = "test_event";
        let distinct_id = Uuid::new_v4().to_string();
        let team_id = 456;
        let payload = create_test_message(event_name, &distinct_id, team_id);

        // Produce message to source_topic after service is ready to consume
        produce_test_message(&producer, &source_topic, payload)
            .await
            .expect("Failed to produce message");

        // Produce a dummy message to dest_topic to ensure it exists before subscribing
        // (topics are auto-created on first produce in mock cluster)
        produce_test_message(&producer, &dest_topic, b"dummy".to_vec())
            .await
            .expect("Failed to create dest_topic");

        // Give the service time to consume and produce to dest_topic
        tokio::time::sleep(Duration::from_millis(1000)).await;

        // prepare and launch the service for the test
        let mut cfg = Config::init_with_defaults().unwrap();
        cfg.kafka_hosts = cluster.bootstrap_servers(); // Use mock cluster bootstrap servers
        cfg.partition_key_compute_fn = "propdefs_v1_by_team_id".to_string();
        cfg.kafka_source_topic = source_topic.clone();
        cfg.kafka_destination_topic = dest_topic.clone();
        cfg.kafka_consumer_offset_reset = "earliest".to_string(); // Start from beginning to consume pre-produced messages
        let svc = RepartitionerService::new(cfg, HealthRegistry::new("test_repartitioner"))
            .await
            .unwrap();
        let svc_handle = tokio::spawn(async move {
            svc.run().await.unwrap();
        });

        // Give the service time to start and subscribe to source_topic
        tokio::time::sleep(Duration::from_millis(200)).await;

        consumer
            .subscribe(&[&dest_topic])
            .expect("Failed to subscribe");

        // Skip the dummy message and wait for the actual message from the service
        let mut message = timeout(Duration::from_secs(5), consumer.recv())
            .await
            .expect("Timeout waiting for message")
            .expect("Failed to receive message");

        // Skip dummy message if present
        if message.payload().map(|p| p == b"dummy").unwrap_or(false) {
            message = timeout(Duration::from_secs(5), consumer.recv())
                .await
                .expect("Timeout waiting for message")
                .expect("Failed to receive message");
        }

        let received_payload = message.payload().expect("Message has no payload");
        assert_eq!(
            String::from_utf8(message.key().unwrap().to_vec()).unwrap(),
            team_id.to_string()
        );

        let received_json: serde_json::Value =
            serde_json::from_slice(received_payload).expect("Failed to parse JSON");

        assert_eq!(received_json["event"], event_name);
        assert_eq!(received_json["distinct_id"], distinct_id);
        assert_eq!(received_json["team_id"].as_i64(), Some(team_id));
        assert_eq!(received_json["project_id"].as_i64(), Some(team_id));
        assert_eq!(received_json["person_mode"], "full");
        assert_eq!(received_json["elements_chain"], "");

        svc_handle.abort();
    }

    #[tokio::test]
    async fn test_service_with_multiple_events() {
        let (cluster, consumer, producer, source_topic, dest_topic) =
            setup_test_environment().await;

        let test_cases = vec![
            ("pageview", Uuid::new_v4().to_string(), 111),
            ("$identify", Uuid::new_v4().to_string(), 222),
            ("custom_event", Uuid::new_v4().to_string(), 333),
        ];

        for (event_name, distinct_id, team_id) in &test_cases {
            let payload = create_test_message(event_name, distinct_id, *team_id);
            produce_test_message(&producer, &source_topic, payload.clone())
                .await
                .expect("Failed to produce message");
        }

        // Produce a dummy message to dest_topic to ensure it exists before subscribing
        // (topics are auto-created on first produce in mock cluster)
        produce_test_message(&producer, &dest_topic, b"dummy".to_vec())
            .await
            .expect("Failed to create dest_topic");

        tokio::time::sleep(Duration::from_millis(1000)).await;

        // prepare and launch the service for the test
        let mut cfg = Config::init_with_defaults().unwrap();
        cfg.kafka_hosts = cluster.bootstrap_servers(); // Use mock cluster bootstrap servers
        cfg.partition_key_compute_fn = "propdefs_v1_by_team_id".to_string();
        cfg.kafka_source_topic = source_topic.clone();
        cfg.kafka_destination_topic = dest_topic.clone();
        cfg.kafka_consumer_offset_reset = "earliest".to_string(); // Start from beginning to consume pre-produced messages
        let svc = RepartitionerService::new(cfg, HealthRegistry::new("test_repartitioner"))
            .await
            .unwrap();
        let svc_handle = tokio::spawn(async move {
            svc.run().await.unwrap();
        });

        // let the service warm up for a moment and process it's inputs
        tokio::time::sleep(Duration::from_millis(200)).await;

        consumer
            .subscribe(&[&dest_topic])
            .expect("Failed to subscribe");

        // clear dummy payload out of the way before checking results
        let dummy_msg = timeout(Duration::from_secs(5), consumer.recv())
            .await
            .expect("Timeout waiting for message")
            .expect("Failed to receive message");
        assert!(dummy_msg.payload().map(|p| p == b"dummy").unwrap_or(false));

        for (event_name, distinct_id, team_id) in &test_cases {
            let message = timeout(Duration::from_secs(5), consumer.recv())
                .await
                .expect("Timeout waiting for message")
                .expect("Failed to receive message");

            let received_payload = message.payload().expect("Message has no payload");
            let received_json: serde_json::Value =
                serde_json::from_slice(received_payload).expect("Failed to parse JSON");

            assert_eq!(received_json["event"], *event_name);
            assert_eq!(received_json["distinct_id"], *distinct_id);
            assert_eq!(received_json["team_id"].as_i64(), Some(*team_id));
            assert_eq!(received_json["project_id"].as_i64(), Some(*team_id));
            assert_eq!(received_json["person_mode"], "full");
        }

        svc_handle.abort();
    }
}
