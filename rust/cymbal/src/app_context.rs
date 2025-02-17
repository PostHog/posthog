use aws_config::{BehaviorVersion, Region};
use common_kafka::{
    kafka_consumer::SingleTopicConsumer, kafka_producer::KafkaContext,
    transaction::TransactionalProducer,
};
use health::{HealthHandle, HealthRegistry};
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::{sync::Arc, time::Duration};
use tokio::sync::Mutex;
use tracing::info;
use uuid::Uuid;

use crate::{
    config::{init_global_state, Config},
    error::UnhandledError,
    frames::resolver::Resolver,
    symbol_store::{
        caching::{Caching, SymbolSetCache},
        concurrency,
        saving::Saving,
        sourcemap::SourcemapProvider,
        Catalog, S3Client,
    },
};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub kafka_consumer: SingleTopicConsumer,
    pub kafka_producer: Mutex<TransactionalProducer<KafkaContext>>,
    pub pool: PgPool,
    pub catalog: Catalog,
    pub resolver: Resolver,
    pub config: Config,
}

impl AppContext {
    pub async fn new(config: &Config) -> Result<Self, UnhandledError> {
        init_global_state(config);
        let health_registry = HealthRegistry::new("liveness");
        let worker_liveness = health_registry
            .register("worker".to_string(), Duration::from_secs(60))
            .await;
        let kafka_liveness = health_registry
            .register("rdkafka".to_string(), Duration::from_secs(30))
            .await;

        let kafka_consumer =
            SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

        let kafka_producer = TransactionalProducer::with_context(
            &config.kafka,
            &Uuid::now_v7().to_string(),
            Duration::from_secs(30),
            KafkaContext::from(kafka_liveness),
        )?;

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        let aws_credentials = aws_sdk_s3::config::Credentials::new(
            &config.object_storage_access_key_id,
            &config.object_storage_secret_access_key,
            None,
            None,
            "environment",
        );
        let aws_conf = aws_sdk_s3::config::Builder::new()
            .region(Region::new(config.object_storage_region.clone()))
            .endpoint_url(&config.object_storage_endpoint)
            .credentials_provider(aws_credentials)
            .behavior_version(BehaviorVersion::latest())
            .build();
        let s3_client = aws_sdk_s3::Client::from_conf(aws_conf);
        let s3_client = S3Client::new(s3_client);

        let ss_cache = Arc::new(Mutex::new(SymbolSetCache::new(
            config.symbol_store_cache_max_bytes,
        )));

        let smp = SourcemapProvider::new(config);
        let saving_smp = Saving::new(
            smp,
            pool.clone(),
            s3_client,
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
        );
        let caching_smp = Caching::new(saving_smp, ss_cache);
        // We want to fetch each sourcemap from the outside world
        // exactly once, and if it isn't in the cache, load/parse
        // it from s3 exactly once too. Limiting the per symbol set
        // reference concurreny to 1 ensures this.
        let limited_smp = concurrency::AtMostOne::new(caching_smp);

        info!(
            "AppContext initialized, subscribed to topic {}",
            config.consumer.kafka_consumer_topic
        );

        let catalog = Catalog::new(limited_smp);
        let resolver = Resolver::new(config);

        Ok(Self {
            health_registry,
            worker_liveness,
            kafka_consumer,
            kafka_producer: Mutex::new(kafka_producer),
            pool,
            catalog,
            resolver,
            config: config.clone(),
        })
    }
}
