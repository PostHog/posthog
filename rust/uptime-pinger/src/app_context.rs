use std::time::Duration;

use anyhow::Result;
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use rdkafka::producer::FutureProducer;
use reqwest::Client as HttpClient;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

use crate::config::Config;

pub struct AppContext {
    pub pool: PgPool,
    pub kafka_producer: FutureProducer<KafkaContext>,
    pub http: HttpClient,
    pub config: Config,
}

impl AppContext {
    pub async fn new<L>(config: Config, kafka_liveness: L) -> Result<Self>
    where
        L: common_liveness::SyncLivenessReporter + Clone + 'static,
    {
        let pool = PgPoolOptions::new()
            .max_connections(config.max_pg_connections)
            .connect(&config.database_url)
            .await?;

        let kafka_producer = create_kafka_producer(&config.kafka, kafka_liveness).await?;

        let http = HttpClient::builder()
            .timeout(Duration::from_secs(config.ping_timeout_seconds))
            // Don't follow redirects past a few hops — sites that 301-loop should fail the ping
            // rather than wedge a worker.
            .redirect(reqwest::redirect::Policy::limited(3))
            .user_agent("PostHog-Uptime-Pinger/1.0")
            .build()?;

        Ok(Self {
            pool,
            kafka_producer,
            http,
            config,
        })
    }
}
