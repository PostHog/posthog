mod common;

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common::{create_topic, kafka_hosts, service_with_resolver, TestLiveness};
use common_kafka_consumer::config::ConsumerConfigBuilder;
use prost::Message as ProstMessage;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::{ClientConfig, Message as KafkaMessage};
use tokio::sync::Barrier;
use usage_ingestion::kafka::{KafkaBatchConfig, KafkaUsageIngestion};
use usage_ingestion::resolver::{OrganizationResolver, ResolveError};
use usage_ingestion_proto::usage_ingestion::v1::{BillingUsageRecord, IngestBillingUsageRequest};
use uuid::Uuid;

struct FixedResolver(Uuid);

#[async_trait]
impl OrganizationResolver for FixedResolver {
    async fn resolve(&self, _team_id: i64) -> Result<Uuid, ResolveError> {
        Ok(self.0)
    }
}

struct BarrierResolver {
    organization_id: Uuid,
    barrier: Arc<Barrier>,
}

#[async_trait]
impl OrganizationResolver for BarrierResolver {
    async fn resolve(&self, _team_id: i64) -> Result<Uuid, ResolveError> {
        self.barrier.wait().await;
        Ok(self.organization_id)
    }
}

fn producer() -> FutureProducer {
    ClientConfig::new()
        .set("bootstrap.servers", kafka_hosts())
        .set("message.timeout.ms", "10000")
        .create()
        .expect("failed to create the test producer")
}

async fn publish(producer: &FutureProducer, topic: &str, partition: i32, payload: &[u8]) {
    producer
        .send(
            FutureRecord::to(topic)
                .key("usage-ingestion-test")
                .payload(payload)
                .partition(partition),
            Timeout::After(Duration::from_secs(10)),
        )
        .await
        .expect("failed to publish the test message");
}

fn consumer_config(group: &str) -> ClientConfig {
    ConsumerConfigBuilder::for_batch_consumer(&kafka_hosts(), group)
        .with_offset_reset("earliest")
        .build()
}

fn request(team_id: i64) -> IngestBillingUsageRequest {
    IngestBillingUsageRequest {
        records: vec![BillingUsageRecord {
            record_id: Uuid::new_v4().to_string(),
            producer_id: "usage-ingestion-kafka-test".to_string(),
            team_id,
            usage_key: "test".to_string(),
            unit: "record".to_string(),
            quantity: 1,
            timestamp_ms: 1_718_409_600_000,
        }],
    }
}

fn batch_config() -> KafkaBatchConfig {
    KafkaBatchConfig {
        max_messages: 100,
        max_wait: Duration::from_millis(50),
        concurrency: 2,
    }
}

#[tokio::test]
#[ignore = "requires a local Kafka; run with --ignored"]
async fn processes_multiple_partitions_concurrently() {
    let input_topic = format!("usage_ingestion_concurrency_{}", Uuid::new_v4());
    let dead_letter_topic = format!("{input_topic}_dlq");
    create_topic(&input_topic, 2).await;
    create_topic(&dead_letter_topic, 1).await;

    let barrier = Arc::new(Barrier::new(3));
    let service = service_with_resolver(
        500,
        Arc::new(BarrierResolver {
            organization_id: Uuid::new_v4(),
            barrier: Arc::clone(&barrier),
        }),
        None,
    )
    .await;
    let config = consumer_config(&format!("usage-ingestion-test-{}", Uuid::new_v4()));
    let transport = KafkaUsageIngestion::new(
        &config,
        &input_topic,
        dead_letter_topic,
        service,
        batch_config(),
        TestLiveness,
    )
    .unwrap();
    let handle = tokio::spawn(async move { transport.run().await });
    let producer = producer();

    publish(&producer, &input_topic, 0, &request(1).encode_to_vec()).await;
    publish(&producer, &input_topic, 1, &request(2).encode_to_vec()).await;

    tokio::time::timeout(Duration::from_secs(10), barrier.wait())
        .await
        .expect("both partitions were not processed concurrently");
    handle.abort();
}

#[tokio::test]
#[ignore = "requires a local Kafka; run with --ignored"]
async fn malformed_input_is_preserved_on_the_dead_letter_topic() {
    let input_topic = format!("usage_ingestion_poison_{}", Uuid::new_v4());
    let dead_letter_topic = format!("{input_topic}_dlq");
    create_topic(&input_topic, 1).await;
    create_topic(&dead_letter_topic, 1).await;

    let group = format!("usage-ingestion-test-{}", Uuid::new_v4());
    let config = consumer_config(&group);
    let service = service_with_resolver(500, Arc::new(FixedResolver(Uuid::new_v4())), None).await;
    let transport = KafkaUsageIngestion::new(
        &config,
        &input_topic,
        dead_letter_topic.clone(),
        service,
        batch_config(),
        TestLiveness,
    )
    .unwrap();
    let handle = tokio::spawn(async move { transport.run().await });

    let dead_letters: StreamConsumer = consumer_config(&format!("{group}-dlq")).create().unwrap();
    dead_letters.subscribe(&[&dead_letter_topic]).unwrap();
    let poison = b"not a protobuf request";
    publish(&producer(), &input_topic, 0, poison).await;

    let message = tokio::time::timeout(Duration::from_secs(10), dead_letters.recv())
        .await
        .expect("the poison message did not reach the dead-letter topic")
        .unwrap();
    assert_eq!(message.payload(), Some(poison.as_slice()));
    assert_eq!(message.key(), Some(b"usage-ingestion-test".as_slice()));
    handle.abort();
}
