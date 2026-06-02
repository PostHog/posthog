use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use common_redis::{Client as RedisClientTrait, RedisClient};
use health::HealthRegistry;
use moka::future::{Cache, CacheBuilder};
use rdkafka::producer::FutureProducer;
use sqlx::{postgres::PgPoolOptions, PgPool};
use std::{sync::Arc, time::Duration};
use tokio::{
    sync::{Mutex, Semaphore},
    task::JoinHandle,
};
use tracing::info;
use uuid::Uuid;

use crate::{
    config::{get_aws_config, init_global_state, Config},
    error::UnhandledError,
    signals::{MaybeSignalClient, SignalClient},
    stages::resolution::remote::{
        dns::TokioDnsResolver, pool::EndpointPool, resolver::RemoteResolutionContext,
        RemoteResolutionConfig,
    },
    stages::resolution::symbol::{local::LocalSymbolResolver, SymbolResolver},
    symbol_store::{
        apple::AppleProvider,
        caching::{Caching, SymbolSetCache},
        chunk_id::ChunkIdFetcher,
        concurrency,
        hermesmap::HermesMapProvider,
        proguard::ProguardProvider,
        saving::Saving,
        sourcemap::SourcemapProvider,
        BlobClient, Catalog, S3Client,
    },
    teams::TeamManager,
    types::operator::TeamId,
};

pub struct AppContext {
    pub health_registry: HealthRegistry,
    pub immediate_producer: FutureProducer<KafkaContext>,
    // Dedicated producer for `cdp_internal_events`. Points at warpstream-cyclotron when
    // `CYMBAL_CYCLOTRON_KAFKA_HOSTS` is set; otherwise falls back to `immediate_producer`.
    pub cyclotron_producer: FutureProducer<KafkaContext>,
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
    pub config: Config,

    pub team_manager: TeamManager,
    pub issue_buckets_redis_client: Arc<dyn RedisClientTrait + Send + Sync>,
    pub signal_client: MaybeSignalClient,
    // Shared `(team_id, fingerprint) -> issue_id` mapping cache. Lives on AppContext so
    // it persists across requests — only the stable mapping is cached, never the Issue
    // itself, so suppression / reopen always see current PG state (see `IssueLinker`).
    // moka caches are cheap to clone (internally Arc'd).
    pub issue_cache: Cache<(TeamId, String), Uuid>,
}

impl Drop for AppContext {
    fn drop(&mut self) {
        if let Some(handle) = &self.remote_resolution_refresh_task {
            handle.abort();
        }
    }
}

/// Build just the symbol-resolution stack from env config: connects to
/// Postgres, builds the S3 client, calls [`init_global_state`], and
/// returns a fully-wired `SymbolResolver`. **Does not** start Kafka
/// producers, Redis clients, signals, the issue cache, or the remote-
/// resolution pool — those belong to the full cymbal pipeline and are
/// constructed by [`AppContext::from_config`].
///
/// Used by `cymbal-resolution`, the standalone gRPC service that only
/// needs symbol resolution; keeping this separate stops cymbal-resolution
/// pods from holding Kafka/Redis connections they never use.
pub async fn build_symbol_resolver(
    config: &Config,
) -> Result<Arc<dyn SymbolResolver>, UnhandledError> {
    init_global_state(config);
    let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
    let posthog_pool = options.connect(&config.database_url).await?;
    let s3 = aws_sdk_s3::Client::from_conf(get_aws_config(config).await);
    let s3_client: Arc<dyn BlobClient> = Arc::new(S3Client::new(s3));
    s3_client.ping_bucket(&config.object_storage_bucket).await?;
    let catalog = build_catalog(config, s3_client, posthog_pool.clone());
    Ok(Arc::new(LocalSymbolResolver::new(
        config,
        catalog,
        posthog_pool,
    )))
}

/// Build the symbol-store [`Catalog`] from already-constructed S3 and PG
/// handles. Internal helper shared by [`AppContext::new`] and
/// [`build_symbol_resolver`] so the provider wiring doesn't drift.
fn build_catalog(
    config: &Config,
    s3_client: Arc<dyn BlobClient>,
    posthog_pool: PgPool,
) -> Arc<Catalog> {
    let ss_cache = Arc::new(Mutex::new(SymbolSetCache::new(
        config.symbol_store_cache_max_bytes,
    )));

    let smp = SourcemapProvider::new(config).with_chunk_id_rescue(
        posthog_pool.clone(),
        s3_client.clone(),
        config.object_storage_bucket.clone(),
    );
    let smp_chunk = ChunkIdFetcher::new(
        smp,
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let smp_saving = Saving::new(
        smp_chunk,
        posthog_pool.clone(),
        s3_client.clone(),
        config.object_storage_bucket.clone(),
        config.ss_prefix.clone(),
    );
    let smp_caching = Caching::new(smp_saving, ss_cache.clone());
    // We want to fetch each sourcemap from the outside world exactly once,
    // and if it isn't in the cache, load/parse it from s3 exactly once too.
    // Limiting the per symbol set reference concurrency to 1 ensures this.
    let smp_atmostonce = concurrency::AtMostOne::new(smp_caching);

    let hmp_chunk = ChunkIdFetcher::new(
        HermesMapProvider {},
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    // Skip the saving layer for HermesMapProvider, since it'll never fetch
    // something from the outside world.
    let hmp_caching = Caching::new(hmp_chunk, ss_cache.clone());
    let hmp_atmostonce = concurrency::AtMostOne::new(hmp_caching);

    let pgp_chunk = ChunkIdFetcher::new(
        ProguardProvider {},
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let pgp_caching = Caching::new(pgp_chunk, ss_cache.clone());
    let pgp_atmostonce = concurrency::AtMostOne::new(pgp_caching);

    let apple_chunk = ChunkIdFetcher::new(
        AppleProvider {},
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let apple_caching = Caching::new(apple_chunk, ss_cache);
    let apple_atmostonce = concurrency::AtMostOne::new(apple_caching);

    Arc::new(Catalog::new(
        smp_atmostonce,
        hmp_atmostonce,
        pgp_atmostonce,
        apple_atmostonce,
    ))
}

impl AppContext {
    pub async fn from_config(config: &Config) -> Result<Self, UnhandledError> {
        let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
        let posthog_pool = options.connect(&config.database_url).await?;

        let s3_client = aws_sdk_s3::Client::from_conf(get_aws_config(config).await);
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
        config: &Config,
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

        s3_client.ping_bucket(&config.object_storage_bucket).await?;

        let catalog = build_catalog(config, s3_client, posthog_pool.clone());

        info!("AppContext initialized");

        let team_manager = TeamManager::new(config);

        let signal_client = if config.signals_api_base_url.is_empty() {
            MaybeSignalClient::disabled()
        } else {
            info!(
                "Signal emission enabled, base_url={}",
                config.signals_api_base_url
            );
            MaybeSignalClient::enabled(SignalClient::new(config))
        };

        let symbol_resolver = Arc::new(LocalSymbolResolver::new(
            config,
            catalog.clone(),
            posthog_pool.clone(),
        ));
        let symbol_resolution_limiter =
            Arc::new(Semaphore::new(config.symbol_resolution_concurrency.max(1)));
        let process_request_limiter =
            Arc::new(Semaphore::new(config.process_max_in_flight_requests.max(1)));

        let issue_cache = CacheBuilder::new(1000)
            .time_to_live(Duration::from_secs(config.issue_cache_ttl_seconds))
            .build();

        let (remote_resolution, remote_resolution_refresh_task) =
            build_remote_resolution(config).await?;

        Ok(Self {
            health_registry,
            immediate_producer,
            cyclotron_producer,
            posthog_pool,
            catalog,
            config: config.clone(),
            symbol_resolution_limiter,
            process_request_limiter,
            team_manager,
            issue_buckets_redis_client,
            signal_client,
            symbol_resolver,
            issue_cache,
            remote_resolution,
            remote_resolution_refresh_task,
        })
    }
}

async fn build_remote_resolution(
    config: &Config,
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
        Some(RemoteResolutionContext {
            pool,
            config: remote_config,
        }),
        Some(refresh_task),
    ))
}
