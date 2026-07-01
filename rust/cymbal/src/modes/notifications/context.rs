use std::time::Duration;

use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use health::HealthRegistry;
use rdkafka::producer::FutureProducer;
use sqlx::{postgres::PgPoolOptions, PgPool};

use crate::core::error::UnhandledError;
use crate::modes::notifications::config::NotificationsConfig;
use crate::modes::notifications::signals::{MaybeSignalClient, SignalClient};

#[derive(Clone)]
pub struct NotificationsContext {
    pub posthog_pool: PgPool,
    pub immediate_producer: FutureProducer<KafkaContext>,
    pub cyclotron_producer: FutureProducer<KafkaContext>,
    pub signal_client: MaybeSignalClient,
    pub embedding_worker_topic: String,
    pub internal_events_topic: String,
}

impl NotificationsContext {
    pub async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        let posthog_pool = PgPoolOptions::new()
            .max_connections(config.max_pg_connections)
            .connect(&config.database_url)
            .await?;
        let immediate_producer = build_immediate_producer(config).await?;

        Ok(Self {
            posthog_pool,
            cyclotron_producer: build_cyclotron_producer(config, &immediate_producer).await?,
            immediate_producer,
            signal_client: build_signal_client(config),
            embedding_worker_topic: config.embedding_worker_topic.clone(),
            internal_events_topic: config.internal_events_topic.clone(),
        })
    }
}

async fn build_immediate_producer(
    config: &NotificationsConfig,
) -> Result<FutureProducer<KafkaContext>, UnhandledError> {
    create_kafka_producer(&config.kafka, kafka_liveness("immediate_kafka").await)
        .await
        .map_err(Into::into)
}

async fn build_cyclotron_producer(
    config: &NotificationsConfig,
    immediate_producer: &FutureProducer<KafkaContext>,
) -> Result<FutureProducer<KafkaContext>, UnhandledError> {
    let Some(hosts) = config
        .cyclotron_kafka_hosts
        .as_deref()
        .filter(|hosts| !hosts.is_empty())
    else {
        return Ok(immediate_producer.clone());
    };

    let mut cyclotron_config = config.kafka.clone();
    cyclotron_config.kafka_hosts = hosts.to_string();
    if let Some(tls) = config.cyclotron_kafka_tls {
        cyclotron_config.kafka_tls = tls;
    }

    create_kafka_producer(&cyclotron_config, kafka_liveness("cyclotron_kafka").await)
        .await
        .map_err(Into::into)
}

fn build_signal_client(config: &NotificationsConfig) -> MaybeSignalClient {
    if config.signals_api_base_url.is_empty() {
        return MaybeSignalClient::disabled();
    }

    MaybeSignalClient::enabled(SignalClient::new_with_parts(
        config.signals_api_base_url.clone(),
        config.internal_api_secret.clone(),
    ))
}

async fn kafka_liveness(component: &str) -> health::HealthHandle {
    HealthRegistry::new("notifications_liveness")
        .register(component.to_string(), Duration::from_secs(30))
        .await
}
