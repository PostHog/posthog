use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use common_redis::{Client as RedisClientTrait, RedisClient};
use health::HealthRegistry;
use moka::future::{Cache, CacheBuilder};
use rdkafka::producer::FutureProducer;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::{collections::HashSet, sync::Arc, time::Duration};
use tokio::{sync::Semaphore, task::JoinHandle};
use tracing::info;
use uuid::Uuid;

use crate::{
    core::config::get_aws_config,
    core::resolver::build_catalog,
    error::UnhandledError,
    modes::processing::config::{init_global_state, ProcessingConfig},
    stages::rate_limiting::RedisRateLimiter,
    stages::resolution::remote::{
        dns::TokioDnsResolver, pool::EndpointPool, resolver::RemoteResolutionContext,
        RemoteResolutionConfig,
    },
    symbolication::symbol::{local::LocalSymbolResolver, SymbolResolver},
    symbolication::symbol_store::{BlobClient, Catalog, S3Client},
    teams::TeamManager,
    types::operator::TeamId,
};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub immediate_producer: FutureProducer<KafkaContext>,
    // Dedicated producer for `cdp_internal_events`. Points at warpstream-cyclotron when
    // `CYMBAL_CYCLOTRON_KAFKA_HOSTS` is set; otherwise falls back to `immediate_producer`.
    pub cyclotron_producer: FutureProducer<KafkaContext>,
    // Dedicated producer for `clickhouse_app_metrics2`. Points at warpstream-ingestion when
    // `CYMBAL_APP_METRICS_KAFKA_HOSTS` is set; otherwise falls back to `immediate_producer`.
    // The primary producer's cluster (warpstream-shared) does not carry that topic.
    pub app_metrics_producer: FutureProducer<KafkaContext>,
    pub posthog_pool: PgPool,
    pub catalog: Arc<Catalog>,
    pub symbol_resolver: Arc<dyn SymbolResolver>,
    pub symbol_resolution_limiter: Arc<Semaphore>,
    pub process_request_limiter: Arc<Semaphore>,
    /// When set, cymbal's resolution stage routes exception resolution to the
    /// remote `cymbal-resolution` service pool instead of running the local
    /// resolver. Built once at startup; the endpoint pool refreshes itself in
    /// the background.
    pub remote_resolution: Option<RemoteResolutionContext>,
    remote_resolution_refresh_task: Option<JoinHandle<()>>,
    pub config: ProcessingConfig,

    pub team_manager: TeamManager,
    pub issue_buckets_redis_client: Arc<dyn RedisClientTrait + Send + Sync>,
    // Error-tracking rate limiter. `None` when disabled (the default), in which
    // case `RateLimitingStage` is a pass-through no-op.
    pub rate_limiter: Option<Arc<RedisRateLimiter>>,
    // Team allowlist for the rate limiter: `None` = all teams, `Some(set)` = only
    // these. Parsed from ERROR_TRACKING_RATE_LIMITER_ENABLED_TEAM_IDS.
    pub rate_limiter_enabled_team_ids: Option<HashSet<i32>>,
    // Shared `(team_id, fingerprint) -> issue_id` mapping cache. Lives on AppContext so
    // it persists across requests — only the stable mapping is cached, never the Issue
    // itself, so suppression / reopen always see current PG state (see `IssueLinker`).
    // moka caches are cheap to clone (internally Arc'd).
    pub issue_cache: Cache<(TeamId, String), Uuid>,
    // Positive cache of fingerprints that already exist in PG. The grouping stage uses it to
    // pick the oldest already-used automatic fingerprint before issue linking runs.
    pub fingerprint_cache: Cache<(TeamId, String), bool>,
}

impl Drop for AppContext {
    fn drop(&mut self) {
        if let Some(handle) = &self.remote_resolution_refresh_task {
            handle.abort();
        }
    }
}

impl AppContext {
    pub async fn from_config(config: &ProcessingConfig) -> Result<Self, UnhandledError> {
        let options = PgPoolOptions::new().max_connections(config.resolver.max_pg_connections);
        let posthog_pool = options.connect(&config.resolver.database_url).await?;

        let s3_client = aws_sdk_s3::Client::from_conf(get_aws_config(&config.resolver).await);
        let s3_client = S3Client::new(s3_client);
        let s3_client = Arc::new(s3_client);

        let issue_buckets_redis_client = RedisClient::with_config(
            config.issue_buckets_redis_url.clone(),
            common_redis::CompressionConfig::disabled(),
            common_redis::RedisValueFormat::default(),
            if config.redis_response_timeout_ms == 0 {
                None
            } else {
                Some(Duration::from_millis(config.redis_response_timeout_ms))
            },
            if config.redis_connection_timeout_ms == 0 {
                None
            } else {
                Some(Duration::from_millis(config.redis_connection_timeout_ms))
            },
        )
        .await?;

        let issue_buckets_redis_client: Arc<dyn RedisClientTrait + Send + Sync> =
            Arc::new(issue_buckets_redis_client);

        AppContext::new(config, s3_client, posthog_pool, issue_buckets_redis_client).await
    }

    pub async fn new(
        config: &ProcessingConfig,
        s3_client: Arc<dyn BlobClient>,
        posthog_pool: PgPool,
        issue_buckets_redis_client: Arc<dyn RedisClientTrait + Send + Sync>,
    ) -> Result<Self, UnhandledError> {
        init_global_state(config);
        let health_registry = HealthRegistry::new("liveness");

        let kafka_immediate_liveness = health_registry
            .register("immediate_kafka".to_string(), Duration::from_secs(30))
            .await;
        let immediate_producer =
            create_kafka_producer(&config.kafka, kafka_immediate_liveness).await?;

        // Build the cyclotron producer if a separate broker list is configured; otherwise
        // reuse the primary producer (so call sites can always target `cyclotron_producer`
        // without branching).
        let cyclotron_producer = match config.cyclotron_kafka_hosts.as_deref() {
            Some(hosts) if !hosts.is_empty() => {
                let mut cyclotron_config = config.kafka.clone();
                cyclotron_config.kafka_hosts = hosts.to_string();
                if let Some(tls) = config.cyclotron_kafka_tls {
                    cyclotron_config.kafka_tls = tls;
                }
                let kafka_cyclotron_liveness = health_registry
                    .register("cyclotron_kafka".to_string(), Duration::from_secs(30))
                    .await;
                create_kafka_producer(&cyclotron_config, kafka_cyclotron_liveness).await?
            }
            _ => immediate_producer.clone(),
        };

        // Build the app-metrics producer if a separate broker list is configured; otherwise
        // reuse the primary producer (so local dev, where one cluster carries every topic,
        // works without extra config).
        let app_metrics_producer = match config.app_metrics_kafka_hosts.as_deref() {
            Some(hosts) if !hosts.is_empty() => {
                let mut app_metrics_config = config.kafka.clone();
                app_metrics_config.kafka_hosts = hosts.to_string();
                if let Some(tls) = config.app_metrics_kafka_tls {
                    app_metrics_config.kafka_tls = tls;
                }
                let kafka_app_metrics_liveness = health_registry
                    .register("app_metrics_kafka".to_string(), Duration::from_secs(30))
                    .await;
                create_kafka_producer(&app_metrics_config, kafka_app_metrics_liveness).await?
            }
            _ => immediate_producer.clone(),
        };

        s3_client
            .ping_bucket(&config.resolver.object_storage_bucket)
            .await?;

        let catalog = build_catalog(&config.resolver, s3_client, posthog_pool.clone());

        info!("AppContext initialized");

        let team_manager = TeamManager::new(config);

        let symbol_resolver = Arc::new(LocalSymbolResolver::new(
            &config.resolver,
            catalog.clone(),
            posthog_pool.clone(),
        ));
        let symbol_resolution_limiter = Arc::new(Semaphore::new(
            config.resolver.symbol_resolution_concurrency.max(1),
        ));
        let process_request_limiter =
            Arc::new(Semaphore::new(config.process_max_in_flight_requests.max(1)));

        let issue_cache = CacheBuilder::new(1000)
            .time_to_live(Duration::from_secs(config.issue_cache_ttl_seconds))
            .build();
        let fingerprint_cache = CacheBuilder::new(1000)
            .time_to_live(Duration::from_secs(config.issue_cache_ttl_seconds))
            .build();

        let (remote_resolution, remote_resolution_refresh_task) =
            build_remote_resolution(config).await?;

        let rate_limiter = build_rate_limiter(config).await?;
        let rate_limiter_enabled_team_ids =
            parse_team_id_allowlist(&config.error_tracking_rate_limiter_enabled_team_ids);

        Ok(Self {
            health_registry,
            immediate_producer,
            cyclotron_producer,
            app_metrics_producer,
            posthog_pool,
            catalog,
            config: config.clone(),
            symbol_resolution_limiter,
            process_request_limiter,
            team_manager,
            issue_buckets_redis_client,
            rate_limiter,
            rate_limiter_enabled_team_ids,
            symbol_resolver,
            issue_cache,
            fingerprint_cache,
            remote_resolution,
            remote_resolution_refresh_task,
        })
    }
}

async fn build_rate_limiter(
    config: &ProcessingConfig,
) -> Result<Option<Arc<RedisRateLimiter>>, UnhandledError> {
    if !config.error_tracking_rate_limiter_enabled {
        return Ok(None);
    }

    // Dedicated connection to the rate-limiter Redis. Defaults to localhost,
    // which is shared with the issue-buckets Redis in local dev.
    let client = RedisClient::with_config(
        config.error_tracking_rate_limiter_redis_url.clone(),
        common_redis::CompressionConfig::disabled(),
        common_redis::RedisValueFormat::Utf8,
        if config.redis_response_timeout_ms == 0 {
            None
        } else {
            Some(Duration::from_millis(config.redis_response_timeout_ms))
        },
        if config.redis_connection_timeout_ms == 0 {
            None
        } else {
            Some(Duration::from_millis(config.redis_connection_timeout_ms))
        },
    )
    .await?;

    info!("Error-tracking rate limiter enabled");

    Ok(Some(Arc::new(RedisRateLimiter::new(
        Arc::new(client),
        config.error_tracking_rate_limiter_key_prefix.clone(),
        config.error_tracking_rate_limiter_bucket_ttl_seconds,
    ))))
}

/// Parse a comma-separated team-id allowlist. `None` (empty input) means the
/// rate limiter applies to all teams; `Some(set)` restricts it to those teams.
fn parse_team_id_allowlist(value: &str) -> Option<HashSet<i32>> {
    if value.is_empty() {
        return None;
    }
    Some(
        value
            .split(',')
            .filter_map(|s| s.trim().parse::<i32>().ok())
            .collect(),
    )
}

async fn build_remote_resolution(
    config: &ProcessingConfig,
) -> Result<(Option<RemoteResolutionContext>, Option<JoinHandle<()>>), UnhandledError> {
    if !config.remote_resolution_enabled {
        return Ok((None, None));
    }

    let remote_config = RemoteResolutionConfig::from_config(config)?;
    info!(
        host = %remote_config.host,
        port = remote_config.port,
        deadline_ms = remote_config.request_deadline.as_millis() as u64,
        dns_refresh_secs = remote_config.dns_refresh.as_secs(),
        max_retries = remote_config.max_retries,
        sample_rate = remote_config.sample_rate,
        "remote resolution enabled, building endpoint pool"
    );

    let resolver = Arc::new(TokioDnsResolver);
    let pool = EndpointPool::new(remote_config.clone(), resolver)
        .await
        .map_err(|e| {
            UnhandledError::Other(format!("failed to build remote resolution pool: {e}"))
        })?;
    let readiness_timeout = std::cmp::max(
        remote_config.subscribe_tick_hint.saturating_mul(3),
        remote_config.connect_timeout,
    );
    pool.wait_ready(readiness_timeout).await.map_err(|e| {
        UnhandledError::Other(format!("remote resolution pool did not become ready: {e}"))
    })?;
    let refresh_task = crate::stages::resolution::remote::pool::spawn_refresh_task(pool.clone());

    Ok((
        Some(RemoteResolutionContext::new(pool, remote_config)),
        Some(refresh_task),
    ))
}
