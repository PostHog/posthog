use std::time::Duration;

use common_kafka::kafka_producer::KafkaContext;
use health::HealthRegistry;
use personhog_proto::personhog::types::v1::Person;
use personhog_writer::store::StoreConfig;
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{DefaultProducerContext, FutureProducer};
use sqlx::postgres::PgPool;

pub const PERSONS_DB_URL: &str = "postgres://posthog:posthog@localhost:5432/posthog_persons";
pub const KAFKA_BOOTSTRAP: &str = "localhost:9092";
pub const TOPIC: &str = "personhog_updates";
pub const TARGET_TABLE: &str = "personhog_person_tmp";

/// StoreConfig with integration-test-sized defaults. Chunk size 500 so
/// multi-chunk batch behavior is exercisable at realistic but small scale,
/// property thresholds match the PG constraint.
pub fn test_store_config() -> StoreConfig {
    StoreConfig {
        chunk_size: 500,
        row_fallback_concurrency: 8,
        properties_size_threshold: 655_360,
        properties_trim_target: 524_288,
    }
}

/// Create a mock Kafka cluster with the personhog_updates topic.
pub async fn create_mock_kafka() -> (
    MockCluster<'static, DefaultProducerContext>,
    FutureProducer<KafkaContext>,
) {
    let (cluster, producer) = common_kafka::test::create_mock_kafka().await;
    cluster
        .create_topic(TOPIC, 1, 1)
        .expect("failed to create mock topic");
    (cluster, producer)
}

/// Create a producer against local Kafka for e2e tests.
pub async fn create_local_kafka_producer() -> FutureProducer<KafkaContext> {
    let registry = HealthRegistry::new("test");
    let handle = registry
        .register("kafka".to_string(), Duration::from_secs(30))
        .await;
    let config = common_kafka::config::KafkaConfig {
        kafka_producer_linger_ms: 0,
        kafka_producer_queue_mib: 50,
        kafka_message_timeout_ms: 5000,
        kafka_compression_codec: "none".to_string(),
        kafka_hosts: KAFKA_BOOTSTRAP.to_string(),
        kafka_tls: false,
        kafka_producer_queue_messages: 1000,
        kafka_client_rack: String::new(),
        kafka_client_id: String::new(),
        kafka_producer_batch_size: None,
        kafka_producer_batch_num_messages: None,
        kafka_producer_enable_idempotence: None,
        kafka_producer_max_in_flight_requests_per_connection: None,
        kafka_producer_topic_metadata_refresh_interval_ms: None,
        kafka_producer_message_max_bytes: None,
        kafka_producer_sticky_partitioning_linger_ms: None,
    };
    common_kafka::kafka_producer::create_kafka_producer(&config, handle)
        .await
        .expect("failed to connect to local Kafka")
}

/// Connect to the local persons database.
pub async fn create_test_pool() -> PgPool {
    PgPool::connect(PERSONS_DB_URL)
        .await
        .expect("failed to connect to persons DB")
}

/// Build a test Person proto.
pub fn make_person(team_id: i64, person_id: i64, version: i64) -> Person {
    Person {
        id: person_id,
        team_id,
        uuid: format!("00000000-0000-0000-0000-{:012}", team_id * 1000 + person_id),
        properties: serde_json::to_vec(&serde_json::json!({"email": "test@example.com"})).unwrap(),
        properties_last_updated_at: vec![],
        properties_last_operation: vec![],
        created_at: 1700000000,
        version,
        is_identified: false,
        is_user_id: None,
        last_seen_at: None,
    }
}

/// Clean up test data from the personhog_person_tmp table for a given team.
pub async fn cleanup_team(pool: &PgPool, team_id: i32) {
    sqlx::query("DELETE FROM personhog_person_tmp WHERE team_id = $1")
        .bind(team_id)
        .execute(pool)
        .await
        .expect("failed to clean up test data");
}
