use anyhow::Result;
use std::{sync::Arc, time::Duration};

use common_database::{get_pool, Client as DatabaseClient};
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use common_redis::{Client as RedisClientTrait, RedisClient};
use health::{HealthHandle, HealthRegistry};
use rdkafka::producer::FutureProducer;

use crate::config::Config;

#[derive(Clone)]
pub struct State {
    pub db_reader_client: Arc<dyn DatabaseClient + Send + Sync>,
    pub external_redis_client: Arc<dyn RedisClientTrait + Send + Sync>,
    pub internal_redis_client: Arc<dyn RedisClientTrait + Send + Sync>,
    pub default_domain_for_public_store: String,
    pub liveness: Arc<HealthRegistry>,
    pub enable_metrics: bool,
    pub internal_events_producer: FutureProducer<KafkaContext>,
    pub events_topic: String,
}

impl State {
    pub async fn from_config(config: &Config) -> Result<Self> {
        let external_redis_client = match RedisClient::new(config.external_link_redis_url.clone()) {
            Ok(client) => Arc::new(client),
            Err(e) => {
                tracing::error!("Failed to create Redis client: {}", e);
                return Err(anyhow::anyhow!("Failed to create Redis client: {}", e));
            }
        };

        let internal_redis_client = match RedisClient::new(config.internal_link_redis_url.clone()) {
            Ok(client) => Arc::new(client),
            Err(e) => {
                tracing::error!("Failed to create Redis client: {}", e);
                return Err(anyhow::anyhow!("Failed to create Redis client: {}", e));
            }
        };

        let reader = match get_pool(&config.read_database_url, config.max_pg_connections).await {
            Ok(client) => {
                tracing::info!("Successfully created read Postgres client");
                Arc::new(client)
            }
            Err(e) => {
                tracing::error!(
                    error = %e,
                    url = %config.read_database_url,
                    max_connections = config.max_pg_connections,
                    "Failed to create read Postgres client"
                );
                return Err(anyhow::anyhow!(
                    "Failed to create read Postgres client: {}",
                    e
                ));
            }
        };

        let health = Arc::new(HealthRegistry::new("liveness"));

        let simple_loop = health
            .register("simple_loop".to_string(), Duration::from_secs(30))
            .await;
        tokio::spawn(liveness_loop(simple_loop));

        let kafka_immediate_liveness = health
            .register(
                "internal_events_producer".to_string(),
                Duration::from_secs(30),
            )
            .await;
        let internal_events_producer =
            create_kafka_producer(&config.kafka, kafka_immediate_liveness)
                .await
                .unwrap();

        Ok(State {
            db_reader_client: reader,
            external_redis_client,
            internal_redis_client,
            liveness: health,
            internal_events_producer,
            events_topic: config.events_topic.clone(),
            default_domain_for_public_store: config.default_domain_for_public_store.clone(),
            enable_metrics: config.enable_metrics,
        })
    }
}

async fn liveness_loop(handle: HealthHandle) {
    loop {
        handle.report_healthy().await;
        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
    }
}
