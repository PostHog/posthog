use common_kafka::{
    kafka_consumer::SingleTopicConsumer, kafka_producer::create_kafka_producer,
    kafka_producer::KafkaContext,
};
use health::{HealthHandle, HealthRegistry};
use rdkafka::producer::FutureProducer;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::{sync::Arc, time::Duration};
use tokio::sync::Mutex;
use tracing::info;

use crate::{
    config::Config,
    error::Error,
    symbol_store::{
        caching::{Caching, SymbolSetCache},
        saving::Saving,
        sourcemap::SourcemapProvider,
        Catalog,
    },
};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub kafka_consumer: SingleTopicConsumer,
    pub kafka_producer: FutureProducer<KafkaContext>,
    pub pool: PgPool,
    pub catalog: Catalog,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, Error> {
        let health_registry = HealthRegistry::new("liveness");
        let worker_liveness = health_registry
            .register("worker".to_string(), Duration::from_secs(60))
            .await;
        let kafka_liveness = health_registry
            .register("rdkafka".to_string(), Duration::from_secs(30))
            .await;

        let kafka_consumer =
            SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;
        let kafka_producer = create_kafka_producer(&config.kafka, kafka_liveness)
            .await
            .expect("failed to create kafka producer");

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        // TODO - this isn't really correct, we should instead specify the relevant vals
        // in `Config`
        let s3_client = aws_sdk_s3::Client::new(&aws_config::from_env().load().await);

        let ss_cache = Arc::new(Mutex::new(SymbolSetCache::new(
            config.symbol_store_cache_max_bytes,
        )));

        let smp = SourcemapProvider::new(config)?;
        let saving_smp = Saving::new(
            smp,
            pool.clone(),
            s3_client,
            config.ss_bucket.clone(),
            config.ss_prefix.clone(),
        );
        let caching_smp = Caching::new(saving_smp, ss_cache);

        info!(
            "AppContext initialized, subscribed to topic {}",
            config.consumer.kafka_consumer_topic
        );

        let catalog = Catalog::new(caching_smp);

        Ok(Self {
            health_registry,
            worker_liveness,
            kafka_consumer,
            kafka_producer,
            pool,
            catalog,
        })
    }
}
