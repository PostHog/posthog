use std::sync::Arc;

use common_database::Client as DatabaseClient;
use common_kafka::kafka_producer::KafkaContext;
use common_redis::Client as RedisClient;
use health::HealthRegistry;
use rdkafka::producer::FutureProducer;

#[derive(Clone)]
pub struct State {
    pub db_reader_client: Arc<dyn DatabaseClient + Send + Sync>,
    pub external_redis_client: Arc<dyn RedisClient + Send + Sync>,
    pub internal_redis_client: Arc<dyn RedisClient + Send + Sync>,
    pub internal_events_producer: FutureProducer<KafkaContext>,
    pub default_domain_for_public_store: String,
    pub liveness: Arc<HealthRegistry>,
    pub enable_metrics: bool,
}
