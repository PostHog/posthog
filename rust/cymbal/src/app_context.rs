use std::time::Duration;

use common_kafka::kafka_consumer::SingleTopicConsumer;
use health::{HealthHandle, HealthRegistry};
use sqlx::{postgres::PgPoolOptions, PgPool};
use tracing::info;

use crate::{
    config::Config,
    error::Error,
    symbol_store::{basic::BasicStore, caching::CachingStore, SymbolStore},
};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub consumer: SingleTopicConsumer,
    pub pool: PgPool,
    pub symbol_store: Box<dyn SymbolStore>,
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

        // We're going to make heavy use of this "layering" pattern with stores, e.g. a we'll add an s3
        // store that wraps an underlying basic one and stores the returned values in s3, and looks in s3
        // before making fetches, etc.
        let symbol_store = BasicStore::new(config)?;
        let symbol_store =
            CachingStore::new(Box::new(symbol_store), config.symbol_store_cache_max_bytes);

        let symbol_store = Box::new(symbol_store);

        Ok(Self {
            health_registry,
            worker_liveness,
            consumer,
            pool,
            symbol_store,
        })
    }
}
