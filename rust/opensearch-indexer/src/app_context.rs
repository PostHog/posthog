use std::time::Duration;

use anyhow::Context;
use common_kafka::kafka_consumer::SingleTopicConsumer;
use common_redis::RedisClient;
use health::{HealthHandle, HealthRegistry};
use reqwest::Client as HttpClient;

use crate::config::Config;

pub struct AppContext {
    pub config: Config,
    pub kafka_consumer: SingleTopicConsumer,
    pub redis: RedisClient,
    pub http: HttpClient,
    pub liveness: HealthRegistry,
    // The work loop reports healthy on this handle. Stage A registers it but
    // does not yet run the loop, so we mark it healthy at startup.
    pub indexer_handle: HealthHandle,
}

impl AppContext {
    pub async fn new(config: Config) -> anyhow::Result<Self> {
        let kafka_consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())
            .context("failed to construct kafka consumer")?;

        let redis = RedisClient::new(config.redis_url.clone())
            .await
            .context("failed to connect to redis")?;

        let http = HttpClient::builder()
            .pool_idle_timeout(Duration::from_secs(30))
            .build()
            .context("failed to build reqwest client")?;

        let liveness = HealthRegistry::new("liveness");
        let indexer_handle = liveness
            .register("indexer".to_string(), Duration::from_secs(60))
            .await;
        // Stage A has no work loop — keep the probe green so mprocs marks the
        // process Up. Stage B replaces this with periodic reports from the loop.
        indexer_handle.report_healthy().await;

        Ok(Self {
            config,
            kafka_consumer,
            redis,
            http,
            liveness,
            indexer_handle,
        })
    }
}
