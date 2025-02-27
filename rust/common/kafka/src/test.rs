use health::HealthRegistry;
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{DefaultProducerContext, FutureProducer};

use crate::config::KafkaConfig;
use crate::kafka_producer::{create_kafka_producer, KafkaContext};

pub async fn create_mock_kafka() -> (
    MockCluster<'static, DefaultProducerContext>,
    FutureProducer<KafkaContext>,
) {
    let registry = HealthRegistry::new("liveness");
    let handle = registry
        .register("one".to_string(), time::Duration::seconds(30))
        .await;
    let cluster = MockCluster::new(1).expect("failed to create mock brokers");

    let config = KafkaConfig {
        kafka_producer_linger_ms: 0,
        kafka_producer_queue_mib: 50,
        kafka_message_timeout_ms: 5000,
        kafka_compression_codec: "none".to_string(),
        kafka_hosts: cluster.bootstrap_servers(),
        kafka_tls: false,
        kafka_producer_queue_messages: 1000,
    };

    (
        cluster,
        create_kafka_producer(&config, handle)
            .await
            .expect("failed to create mocked kafka producer"),
    )
}
