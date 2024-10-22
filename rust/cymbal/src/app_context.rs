use std::time::Duration;

use common_kafka::kafka_consumer::SingleTopicConsumer;
use health::{HealthHandle, HealthRegistry};
use sqlx::{postgres::PgPoolOptions, PgPool};
use tracing::info;

use crate::{
    config::Config,
    error::Error,
    symbol_store::{ sourcemap::SourcemapProvider, Catalog},
};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub consumer: SingleTopicConsumer,
    pub pool: PgPool,
    pub catalog: Catalog,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, Error> {
        let health_registry = HealthRegistry::new("liveness");
        let worker_liveness = health_registry
            .register("worker".to_string(), Duration::from_secs(60))
            .await;

        let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        info!(
            "AppContext initialized, subscribed to topic {}",
            config.consumer.kafka_consumer_topic
        );

        let catalog = Catalog::new(
            config.symbol_store_cache_max_bytes,
            SourcemapProvider::new(config)?,
        );

        Ok(Self {
            health_registry,
            worker_liveness,
            consumer,
            pool,
            catalog,
        })
    }
}
