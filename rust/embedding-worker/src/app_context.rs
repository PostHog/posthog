use std::{sync::Arc, time::Duration};

use anyhow::Result;
use common_kafka::{
    kafka_consumer::SingleTopicConsumer, kafka_producer::KafkaContext,
    transaction::TransactionalProducer,
};
use common_types::embedding::ApiLimits;
use health::{HealthHandle, HealthRegistry};
use moka::sync::{Cache, CacheBuilder};
use sqlx::{postgres::PgPoolOptions, PgPool};
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    config::Config,
    organization::Organization,
    provider::EmbeddingClient,
    recently_seen::{build_store, RecentlySeenStore},
};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub kafka_consumer: SingleTopicConsumer,
    pub transactional_producer: Mutex<TransactionalProducer<KafkaContext>>,
    pub pool: PgPool,
    pub config: Config,
    pub embeddings: EmbeddingClient,
    pub org_cache: Cache<i32, Option<Organization>>,
    pub recently_seen: Arc<dyn RecentlySeenStore>,
}

impl AppContext {
    pub async fn new(config: Config) -> Result<Self> {
        let health_registry = HealthRegistry::new("liveness");
        let worker_liveness = health_registry
            .register("worker".to_string(), Duration::from_secs(60))
            .await;

        let kafka_consumer =
            SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

        let kafka_transactional_liveness = health_registry
            .register("transactional_kafka".to_string(), Duration::from_secs(30))
            .await;

        let transactional_producer = TransactionalProducer::with_context(
            &config.kafka,
            &Uuid::now_v7().to_string(),
            Duration::from_secs(10),
            KafkaContext::from(kafka_transactional_liveness),
        )?;

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(
                config.embedding_request_timeout_seconds,
            ))
            .build()?;

        let embeddings = EmbeddingClient::new(
            client,
            config.openai_api_key.clone(),
            ApiLimits {
                requests_per_minute: config.embedding_requests_per_minute,
                tokens_per_minute: config.embedding_tokens_per_minute,
            },
        )?;

        let org_cache = CacheBuilder::new(10_000)
            .time_to_live(Duration::from_secs(30))
            .build();

        let recently_seen = build_store(&config).await?;

        Ok(Self {
            health_registry,
            worker_liveness,
            kafka_consumer,
            transactional_producer: Mutex::new(transactional_producer),
            pool,
            config,
            embeddings,
            org_cache,
            recently_seen,
        })
    }
}
