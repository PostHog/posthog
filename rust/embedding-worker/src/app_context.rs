use std::{collections::HashMap, sync::Arc, time::Duration};

use anyhow::Result;
use common_kafka::{
    config::KafkaConfig, error::is_transient, kafka_consumer::SingleTopicConsumer,
    kafka_producer::KafkaContext, transaction::TransactionalProducer,
};
use common_types::embedding::{ApiLimits, EmbeddingModel};
use health::{HealthHandle, HealthRegistry};
use leaky_bucket::RateLimiter;
use metrics::{counter, gauge};
use moka::sync::{Cache, CacheBuilder};
use rdkafka::error::KafkaError;
use reqwest::Response;
use sqlx::{postgres::PgPoolOptions, PgPool};
use tokio::sync::{Mutex, RwLock};
use tracing::warn;
use uuid::Uuid;

use crate::{
    config::Config,
    metrics_utils::{LIMITS_UPDATED, LIMIT_BALANCE},
    organization::Organization,
    recently_seen::{build_store, RecentlySeenStore},
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
    pub recently_seen: Arc<dyn RecentlySeenStore>,
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

        let transactional_producer =
            connect_transactional_producer(&config.kafka, &kafka_transactional_liveness).await?;

        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let pool = options.connect(&config.database_url).await?;

        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(
                config.embedding_request_timeout_seconds,
            ))
            .build()?;

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
            client,
            org_cache,
            recently_seen,
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

const KAFKA_CONNECT_ATTEMPTS: u32 = 6;
const KAFKA_CONNECT_FIRST_BACKOFF: Duration = Duration::from_secs(1);
// This bounds `init_transactions`, not the metadata ping before it. A
// producer built without a broker transaction bound pings on the shared
// 15s default, so one attempt can cost 25s. Six attempts, plus the 31s of
// backoff, can hold startup for about 3 minutes before the worker exits.
const KAFKA_TXN_INIT_TIMEOUT: Duration = Duration::from_secs(10);

async fn connect_transactional_producer(
    config: &KafkaConfig,
    liveness: &HealthHandle,
) -> Result<TransactionalProducer<KafkaContext>, KafkaError> {
    // One id for every attempt: a retry claims the same transactional
    // identity, and fences the same previous owner, as the first try.
    let transactional_id = Uuid::now_v7().to_string();

    retry_kafka_connect(|| {
        TransactionalProducer::with_context(
            config,
            &transactional_id,
            KAFKA_TXN_INIT_TIMEOUT,
            KafkaContext::from(liveness.clone()),
        )
    })
    .await
}

/// The startup connect to Kafka fetches metadata and claims the transactional
/// id, so a broker that restarts, or a broker name that does not resolve yet,
/// stops the worker. Retry a bounded number of times, so a blip of a few
/// seconds costs the worker a delay instead of a restart.
async fn retry_kafka_connect<T>(
    mut attempt_fn: impl FnMut() -> Result<T, KafkaError>,
) -> Result<T, KafkaError> {
    let mut backoff = KAFKA_CONNECT_FIRST_BACKOFF;
    let mut attempt = 1;
    loop {
        let error = match attempt_fn() {
            Ok(value) => return Ok(value),
            Err(error) => error,
        };

        if attempt >= KAFKA_CONNECT_ATTEMPTS || !is_transient(&error) {
            return Err(error);
        }

        warn!(
            "Failed to connect to Kafka on attempt {attempt}: {error:?}. Next try in {backoff:?}"
        );
        tokio::time::sleep(backoff).await;
        backoff *= 2;
        attempt += 1;
    }
}

// leaky-bucket adds `refill` tokens once per `interval`. Refilling the whole
// per-minute budget in a single 60s lump means a drained bucket suspends the
// next acquire() until the minute boundary - up to ~60s - which stalls the
// worker's liveness heartbeat and gets the pod killed. Drip the budget in small
// sub-second increments instead, so a drained bucket only ever blocks for about
// one interval. Long-run throughput is unchanged (still capped at the budget).
const REFILL_INTERVAL: Duration = Duration::from_millis(100);
const REFILLS_PER_MINUTE: usize = 600; // 60_000ms / 100ms

fn build_rate_limiter(per_minute: usize) -> RateLimiter {
    RateLimiter::builder()
        .max(per_minute.max(1))
        .initial(per_minute)
        .refill((per_minute / REFILLS_PER_MINUTE).max(1))
        .interval(REFILL_INTERVAL)
        .build()
}

impl From<ApiLimits> for Limiter {
    fn from(definition: ApiLimits) -> Self {
        Limiter {
            tokens: build_rate_limiter(definition.tokens_per_minute),
            requests: build_rate_limiter(definition.requests_per_minute),
            definition,
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

#[cfg(test)]
mod tests {
    use super::*;

    fn transient() -> KafkaError {
        KafkaError::MetadataFetch(rdkafka::error::RDKafkaErrorCode::BrokerTransportFailure)
    }

    #[tokio::test(start_paused = true)]
    async fn retry_survives_a_broker_blip() {
        let mut calls = 0;
        let result = retry_kafka_connect(|| {
            calls += 1;
            if calls < 3 {
                return Err(transient());
            }
            Ok(calls)
        })
        .await;

        assert_eq!(
            result.expect("a transient failure must not end the retry"),
            3
        );
    }

    #[tokio::test(start_paused = true)]
    async fn retry_gives_up_after_the_attempt_bound() {
        let mut calls = 0;
        let result: Result<(), KafkaError> = retry_kafka_connect(|| {
            calls += 1;
            Err(transient())
        })
        .await;

        assert!(result.is_err());
        assert_eq!(calls, KAFKA_CONNECT_ATTEMPTS);
    }

    #[tokio::test(start_paused = true)]
    async fn retry_reports_a_permanent_failure_at_once() {
        // Bad credentials or bad configuration stay broken, so a retry only
        // delays the report the operator needs.
        let mut calls = 0;
        let result: Result<(), KafkaError> = retry_kafka_connect(|| {
            calls += 1;
            Err(KafkaError::ClientCreation("bad configuration".to_string()))
        })
        .await;

        assert!(result.is_err());
        assert_eq!(calls, 1);
    }

    #[tokio::test(start_paused = true)]
    async fn drained_rate_limiter_refills_within_one_interval() {
        // 600/min => 1 token dripped every 100ms.
        let limiter = build_rate_limiter(600);

        // Drain the full initial balance, then acquire one more token. With the old
        // 60s-lump refill this acquire blocks until the minute boundary; with the
        // sub-second drip it must be satisfied within roughly one interval. Paused
        // time auto-advances to the next timer, so the 1s ceiling fails fast if the
        // refill cadence ever regresses to ~60s.
        limiter.acquire(600).await;

        tokio::time::timeout(Duration::from_secs(1), limiter.acquire(1))
            .await
            .expect("drained limiter should refill within ~100ms, well under 60s");
    }
}
