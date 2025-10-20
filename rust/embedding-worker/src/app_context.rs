use std::{collections::HashMap, time::Duration};

use anyhow::Result;
use common_kafka::{
    kafka_consumer::SingleTopicConsumer, kafka_producer::KafkaContext,
    transaction::TransactionalProducer,
};
use common_types::embedding::{ApiLimits, EmbeddingModel};
use health::{HealthHandle, HealthRegistry};
use leaky_bucket::RateLimiter;
use metrics::{counter, gauge};
use moka::sync::{Cache, CacheBuilder};
use reqwest::Response;
use sqlx::{postgres::PgPoolOptions, PgPool};
use tokio::sync::{Mutex, RwLock};
use tracing::warn;
use uuid::Uuid;

use crate::{
    config::Config,
    metrics_utils::{LIMITS_UPDATED, LIMIT_BALANCE},
    organization::Organization,
};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub worker_liveness: HealthHandle,
    pub kafka_consumer: SingleTopicConsumer,
    pub transactional_producer: Mutex<TransactionalProducer<KafkaContext>>,
    pub pool: PgPool,
    pub config: Config,
    pub client: reqwest::Client,
    pub org_cache: Cache<i32, Option<Organization>>,
    rate_limits: RwLock<HashMap<String, Limiter>>,
}

struct Limiter {
    pub definition: ApiLimits,
    pub tokens: RateLimiter,
    pub requests: RateLimiter,
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

        let client = reqwest::Client::new();

        let org_cache = CacheBuilder::new(10_000)
            .time_to_live(Duration::from_secs(30))
            .build();

        Ok(Self {
            health_registry,
            worker_liveness,
            kafka_consumer,
            transactional_producer: Mutex::new(transactional_producer),
            pool,
            config,
            client,
            org_cache,
            rate_limits: Default::default(),
        })
    }

    pub async fn respect_rate_limits(&self, model: EmbeddingModel, tokens: usize) {
        let read = self.rate_limits.read().await;

        let Some(limiter) = read.get(model.limits_key()) else {
            drop(read);
            let mut write = self.rate_limits.write().await;
            write.insert(model.limits_key().to_string(), model.api_limits().into());
            drop(write);

            let read = self.rate_limits.read().await;
            let limiter = read.get(model.limits_key()).expect("We just inserted this");

            limiter.report_balance(model);
            limiter.acquire(tokens, 1).await;
            return;
        };

        limiter.report_balance(model);
        limiter.acquire(tokens, 1).await;
    }

    pub async fn update_rate_limits(&self, model: EmbeddingModel, response: &Response) {
        let header_fn = |key: &str| {
            response
                .headers()
                .get(key)
                .and_then(|v| v.to_str().ok())
                .map(|s| s.to_string())
        };

        if let Some(new_limits) = model.api_limits_from_response(&header_fn) {
            // Do we need to update? We do this here, rather than inside the Limiter,
            // because it lets us only take a read lock on the happy path
            let needs_update = self
                .rate_limits
                .read()
                .await
                .get(model.limits_key())
                .map(|l| l.needs_update(&new_limits))
                .unwrap_or(true); // If we don't find a limiter for this model, we need to add one
            if !needs_update {
                return; // Bail early, never taking a write lock
            }

            counter!(LIMITS_UPDATED, &[("key", model.limits_key())]).increment(1);
            warn!(
                "Updating rate limits for {}: {:?}",
                model.limits_key(),
                new_limits
            );

            let mut write = self.rate_limits.write().await;
            match write.get_mut(model.limits_key()) {
                Some(limiter) => {
                    limiter.update(new_limits).await;
                }
                None => {
                    write.insert(model.limits_key().to_string(), new_limits.into());
                }
            }
        }
    }
}

impl From<ApiLimits> for Limiter {
    fn from(definition: ApiLimits) -> Self {
        let tokens = RateLimiter::builder()
            .max(definition.tokens_per_minute)
            .refill(definition.tokens_per_minute)
            .initial(definition.tokens_per_minute)
            .interval(Duration::from_secs(60))
            .build();
        let requests = RateLimiter::builder()
            .max(definition.requests_per_minute)
            .refill(definition.requests_per_minute)
            .initial(definition.requests_per_minute)
            .interval(Duration::from_secs(60))
            .build();
        Limiter {
            definition,
            tokens,
            requests,
        }
    }
}

impl Limiter {
    pub async fn acquire(&self, tokens: usize, requests: usize) {
        self.tokens.acquire(tokens).await;
        self.requests.acquire(requests).await;
    }

    pub fn report_balance(&self, model: EmbeddingModel) {
        gauge!(
            LIMIT_BALANCE,
            &[("key", model.limits_key()), ("type", "tokens")]
        )
        .set(self.tokens.balance() as f64);
        gauge!(
            LIMIT_BALANCE,
            &[("key", model.limits_key()), ("type", "requests")]
        )
        .set(self.requests.balance() as f64);
    }

    pub fn needs_update(&self, new_limits: &ApiLimits) -> bool {
        self.definition != *new_limits
    }

    pub async fn update(&mut self, new_limits: ApiLimits) {
        let to_consume_tokens = self
            .definition
            .tokens_per_minute
            .saturating_sub(self.tokens.balance());
        let to_consume_requests = self
            .definition
            .requests_per_minute
            .saturating_sub(self.requests.balance());

        *self = new_limits.into();

        self.acquire(to_consume_tokens, to_consume_requests).await;
    }
}
