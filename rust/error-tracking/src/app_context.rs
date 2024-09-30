use std::time::Duration;

use common_kafka::kafka_consumer::SingleTopicConsumer;
use health::{HealthHandle, HealthRegistry};
use tracing::info;

use crate::{config::Config, error::Error};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub consumer: SingleTopicConsumer,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, Error> {
        let health_registry = HealthRegistry::new("liveness");
        let worker_liveness = health_registry
            .register("worker".to_string(), Duration::from_secs(60))
            .await;

        let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

        info!(
            "AppContext initialized, subscribed to topic {}",
            config.consumer.kafka_consumer_topic
        );

        Ok(Self {
            health_registry,
            worker_liveness,
            consumer,
        })
    }
}
