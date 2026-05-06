use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use crate::billing::{
    BillingAggregator, BillingAggregatorConfig, FeatureFlagsLimiter, SessionReplayLimiter,
};
use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::cohorts::membership::{
    CachedCohortMembershipProvider, CohortMembershipProvider, NoOpCohortMembershipProvider,
    RealtimeCohortMembershipProvider,
};
use crate::config::{Config, TeamIdCollection};
use crate::database_pools::DatabasePools;
use crate::db_monitor::DatabasePoolMonitor;
use crate::flags::flag_definitions_cache::FlagDefinitionsCache;
use crate::flags::flag_group_type_mapping::GroupTypeCacheManager;
use crate::rayon_dispatcher::RayonDispatcher;
use crate::router;
use crate::tokio_monitor::TokioRuntimeMonitor;
use common_cache::NegativeCache;
use common_cookieless::CookielessManager;
use common_geoip::GeoIpClient;
use common_hypercache::{HyperCacheConfig, HyperCacheReader};
use common_redis::{
    Client, CompressionConfig, ReadWriteClient, ReadWriteClientConfig, RedisClient,
};
use lifecycle::{ComponentOptions, Handle, LivenessHandler, Manager, ReadinessHandler};
use limiters::redis::QUOTA_LIMITER_CACHE_KEY;
use tokio::net::TcpListener;
use tokio_retry::strategy::{jitter, ExponentialBackoff};
use tokio_retry::Retry;

/// Handles for every lifecycle component this service registers, plus the readiness
/// and liveness handlers the HTTP router needs. Produced by [`register_components`]
/// and passed into [`serve`].
pub struct LifecycleHandles {
    pub http: Handle,
    pub db_monitor: Handle,
    pub cohort_cache_monitor: Handle,
    pub flag_defs_cache_monitor: Handle,
    pub tokio_monitor: Handle,
    pub readiness: ReadinessHandler,
    pub liveness: LivenessHandler,
}

/// Register the feature-flags lifecycle components and return handles for use by
/// `serve()` (and by the test harness). Call this exactly once per Manager, before
/// `manager.monitor_background()`.
///
/// `/_liveness` is hardcoded to 200 (see `lifecycle::LivenessHandler`) and no
/// component opts into `with_liveness_deadline`. For this service, if the tokio
/// runtime can serve the endpoint the process is alive — there's no meaningful
/// internal signal beyond that, and a heartbeat loop would just be checking that
/// the heartbeat itself still runs. Do not add deadlines or `report_healthy()`
/// calls here unless a real signal appears (e.g. the way capture feeds kafka
/// producer health into its handle).
pub fn register_components(manager: &mut Manager) -> LifecycleHandles {
    let http = manager.register(
        "http-server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );
    let db_monitor = manager.register(
        "db-pool-monitor",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(2)),
    );
    let cohort_cache_monitor = manager.register(
        "cohort-cache-monitor",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(2)),
    );
    let flag_defs_cache_monitor = manager.register(
        "flag-definitions-cache-monitor",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(2)),
    );
    let tokio_monitor = manager.register(
        "tokio-runtime-monitor",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(2)),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    LifecycleHandles {
        http,
        db_monitor,
        cohort_cache_monitor,
        flag_defs_cache_monitor,
        tokio_monitor,
        readiness,
        liveness,
    }
}

impl LifecycleHandles {
    /// Surface an init-time error to the lifecycle manager as a `Failure` on the http
    /// component (so the trigger log reads `trigger_reason="failure" reason="…"` instead
    /// of a misleading `Died { tag: "http-server" }`), and pre-complete the unstarted
    /// monitor handles so their drops don't fan out "died during shutdown" warnings in
    /// Phase 2. Call before each early `return` from `serve()`.
    fn fail_init(&self, reason: impl Into<String>) {
        self.http.signal_failure(reason);
        self.http.work_completed();
        self.db_monitor.work_completed();
        self.cohort_cache_monitor.work_completed();
        self.flag_defs_cache_monitor.work_completed();
        self.tokio_monitor.work_completed();
    }
}

pub async fn serve(
    config: Config,
    listener: TcpListener,
    rayon_dispatcher: RayonDispatcher,
    handles: LifecycleHandles,
) {
    // Configure compression based on environment variable
    let compression_config = if *config.redis_compression_enabled {
        let config = CompressionConfig::default();
        tracing::info!(
            "Redis compression enabled (threshold: {} bytes)",
            config.threshold
        );
        config
    } else {
        tracing::info!("Redis compression disabled");
        CompressionConfig::disabled()
    };

    // Create ReadWriteClient for shared Redis (non-critical path: analytics, billing, cookieless)
    // "shared" means the Redis client shares the cache with the Django PostHog web app.
    // Automatically routes reads to replica and writes to primary
    let Some(redis_client) = create_readwrite_client(
        config.get_redis_writer_url(),
        config.get_redis_reader_url(),
        "shared",
        compression_config.clone(),
        config.redis_response_timeout_ms,
        config.redis_connection_timeout_ms,
        config.redis_client_retry_count,
    )
    .await
    else {
        handles.fail_init("shared redis init failed");
        return;
    };

    // Create dedicated ReadWriteClient for flags cache (critical path isolation)
    let dedicated_redis_client =
        create_dedicated_readwrite_client(&config, compression_config.clone()).await;

    // Log the cache migration mode based on configuration
    let cache_mode = match (
        dedicated_redis_client.is_some(),
        *config.flags_redis_enabled,
    ) {
        (false, _) => "Mode 1 (Shared-only): All caches use shared Redis",
        (true, false) => {
            "Mode 2 (Dual-write): Reading from shared Redis, warming dedicated Redis in background"
        }
        (true, true) => "Mode 3 (Dedicated-only): All flags caches use dedicated Redis",
    };
    tracing::info!("Feature flags cache migration mode: {}", cache_mode);

    // Create database pools with persons routing support
    let database_pools = match DatabasePools::from_config(&config).await {
        Ok(pools) => {
            tracing::info!("Successfully created database pools");
            if config.is_persons_db_routing_enabled() {
                tracing::info!("Persons database routing is enabled");
            }
            Arc::new(pools)
        }
        Err(e) => {
            tracing::error!(
                error = %e,
                "Failed to create database pools"
            );
            handles.fail_init(format!("database pools init failed: {e}"));
            return;
        }
    };

    let geoip_service = match GeoIpClient::new(config.get_maxmind_db_path()) {
        Ok(service) => Arc::new(service),
        Err(e) => {
            tracing::error!(
                "Failed to create GeoIP service with DB path {}: {}",
                config.get_maxmind_db_path().display(),
                e
            );
            handles.fail_init(format!("geoip init failed: {e}"));
            return;
        }
    };

    let cohort_cache = Arc::new(CohortCacheManager::new(
        database_pools.non_persons_reader.clone(),
        Some(config.cohort_cache_capacity_bytes),
        Some(config.cache_ttl_seconds),
    ));

    let flag_definitions_cache = Arc::new(FlagDefinitionsCache::new(
        Some(config.flag_definitions_cache_capacity_bytes),
        Some(config.flag_definitions_cache_ttl_seconds),
    ));

    let group_type_cache = Arc::new(GroupTypeCacheManager::new(
        database_pools.persons_reader.clone(),
        Some(config.group_type_cache_max_entries),
        Some(config.group_type_cache_ttl_seconds),
    ));

    // Initialize the cohort membership provider for realtime/behavioral cohorts.
    // Requires both the behavioral cohorts DB pool AND a non-empty team ID collection.
    // When "none" (default), NoOp is used regardless of DB availability,
    // so no realtime cohort queries hit the hot path.
    let cohort_membership_provider: Arc<dyn CohortMembershipProvider> =
        if config.realtime_cohort_evaluation_team_ids != TeamIdCollection::None {
            if let Some(pool) = database_pools.behavioral_cohorts_reader.clone() {
                let realtime = RealtimeCohortMembershipProvider::new(pool);
                Arc::new(CachedCohortMembershipProvider::new(
                    realtime,
                    Some(config.cohort_membership_cache_ttl_seconds),
                    Some(config.cohort_membership_cache_max_entries),
                ))
            } else {
                Arc::new(NoOpCohortMembershipProvider)
            }
        } else {
            Arc::new(NoOpCohortMembershipProvider)
        };

    let feature_flags_billing_limiter = match FeatureFlagsLimiter::new(
        Duration::from_secs(config.billing_limiter_cache_ttl_secs),
        redis_client.clone(), // Limiter only reads from redis, ReadWriteClient automatically routes reads to replica
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
    ) {
        Ok(limiter) => limiter,
        Err(e) => {
            tracing::error!("Failed to create feature flags billing limiter: {}", e);
            handles.fail_init(format!("feature flags billing limiter init failed: {e}"));
            return;
        }
    };

    let session_replay_billing_limiter = match SessionReplayLimiter::new(
        Duration::from_secs(config.billing_limiter_cache_ttl_secs),
        redis_client.clone(), // Limiter only reads from redis, ReadWriteClient automatically routes reads to replica
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
    ) {
        Ok(limiter) => limiter,
        Err(e) => {
            tracing::error!("Failed to create session replay billing limiter: {}", e);
            handles.fail_init(format!("session replay billing limiter init failed: {e}"));
            return;
        }
    };

    let Some(redis_cookieless_client) = create_redis_client(
        &config.get_redis_cookieless_url(),
        "cookieless",
        compression_config.clone(),
        config.redis_response_timeout_ms,
        config.redis_connection_timeout_ms,
        config.redis_client_retry_count,
    )
    .await
    else {
        handles.fail_init("cookieless redis init failed");
        return;
    };

    let cookieless_manager = Arc::new(CookielessManager::new(
        config.get_cookieless_config(),
        redis_cookieless_client.clone(),
    ));

    // Create HyperCacheReader for feature flags at startup
    // This avoids per-request AWS SDK initialization overhead
    let flags_redis_client = dedicated_redis_client
        .clone()
        .unwrap_or_else(|| redis_client.clone());

    let mut flags_hypercache_config = HyperCacheConfig::new(
        "feature_flags".to_string(),
        "flags.json".to_string(),
        config.object_storage_region.clone(),
        config.object_storage_bucket.clone(),
    );

    if !config.object_storage_endpoint.is_empty() {
        flags_hypercache_config.s3_endpoint = Some(config.object_storage_endpoint.clone());
    }

    let flags_hypercache_reader =
        match HyperCacheReader::new(flags_redis_client, flags_hypercache_config).await {
            Ok(reader) => {
                tracing::info!("Created HyperCacheReader for feature flags");
                Arc::new(reader)
            }
            Err(e) => {
                tracing::error!("Failed to create flags HyperCacheReader: {:?}", e);
                handles.fail_init(format!("flags hypercache init failed: {e:?}"));
                return;
            }
        };

    // Create HyperCacheReader for team metadata at startup
    // Uses token-based lookup instead of team_id
    let team_redis_client = dedicated_redis_client
        .clone()
        .unwrap_or_else(|| redis_client.clone());

    let mut team_hypercache_config = HyperCacheConfig::new(
        "team_metadata".to_string(),
        "full_metadata.json".to_string(),
        config.object_storage_region.clone(),
        config.object_storage_bucket.clone(),
    );
    team_hypercache_config.token_based = true;

    if !config.object_storage_endpoint.is_empty() {
        team_hypercache_config.s3_endpoint = Some(config.object_storage_endpoint.clone());
    }

    let team_hypercache_reader =
        match HyperCacheReader::new(team_redis_client, team_hypercache_config).await {
            Ok(reader) => {
                tracing::info!("Created HyperCacheReader for team metadata");
                Arc::new(reader)
            }
            Err(e) => {
                tracing::error!("Failed to create team HyperCacheReader: {:?}", e);
                handles.fail_init(format!("team hypercache init failed: {e:?}"));
                return;
            }
        };

    // Create HyperCacheReader for flags with cohorts (used by /flags/definitions endpoint)
    // Uses the shared cache (redis_client) - same cache Django writes to via HyperCache
    let flags_with_cohorts_redis_client = redis_client.clone();

    let mut flags_with_cohorts_config = HyperCacheConfig::new(
        "feature_flags".to_string(),
        "flags_with_cohorts.json".to_string(),
        config.object_storage_region.clone(),
        config.object_storage_bucket.clone(),
    );

    if !config.object_storage_endpoint.is_empty() {
        flags_with_cohorts_config.s3_endpoint = Some(config.object_storage_endpoint.clone());
    }

    let flags_with_cohorts_hypercache_reader =
        match HyperCacheReader::new(flags_with_cohorts_redis_client, flags_with_cohorts_config)
            .await
        {
            Ok(reader) => {
                tracing::info!("Created HyperCacheReader for flags with cohorts");
                Arc::new(reader)
            }
            Err(e) => {
                tracing::error!(
                    "Failed to create flags with cohorts HyperCacheReader: {:?}",
                    e
                );
                handles.fail_init(format!("flags with cohorts hypercache init failed: {e:?}"));
                return;
            }
        };

    // Create HyperCacheReader for remote config (array/config.json)
    // This reads the pre-computed config blob from Python's RemoteConfig.build_config()
    // Uses token-based lookup (api_token) to match Python's HyperCache key pattern
    let config_redis_client = dedicated_redis_client
        .clone()
        .unwrap_or_else(|| redis_client.clone());

    let mut config_hypercache_config = HyperCacheConfig::new(
        "array".to_string(),
        "config.json".to_string(),
        config.object_storage_region.clone(),
        config.object_storage_bucket.clone(),
    );
    config_hypercache_config.token_based = true;

    if !config.object_storage_endpoint.is_empty() {
        config_hypercache_config.s3_endpoint = Some(config.object_storage_endpoint.clone());
    }

    let config_hypercache_reader =
        match HyperCacheReader::new(config_redis_client, config_hypercache_config).await {
            Ok(reader) => {
                tracing::info!("Created HyperCacheReader for remote config");
                Arc::new(reader)
            }
            Err(e) => {
                tracing::error!("Failed to create config HyperCacheReader: {:?}", e);
                handles.fail_init(format!("config hypercache init failed: {e:?}"));
                return;
            }
        };

    let team_negative_cache = NegativeCache::new(
        config.team_negative_cache_capacity,
        config.team_negative_cache_ttl_seconds,
    );
    tracing::info!(
        capacity = config.team_negative_cache_capacity,
        ttl_seconds = config.team_negative_cache_ttl_seconds,
        "Created team negative cache for invalid API tokens"
    );

    // Auth token cache: read-through cache for secret + personal API key validation.
    // Uses the flags Redis client for cache reads/writes. No in-memory negative cache —
    // Python signal handlers invalidate Redis on scope/key changes, but cannot reach
    // Rust's in-memory cache, which would cause stale denials.
    let auth_redis = dedicated_redis_client
        .clone()
        .unwrap_or_else(|| redis_client.clone());
    let auth_token_inner = Arc::new(common_cache::ReadThroughCache::new(
        auth_redis.clone(),
        auth_redis,
        common_cache::CacheConfig::with_ttl(
            crate::api::auth::TOKEN_CACHE_PREFIX,
            config.auth_token_cache_ttl_seconds,
        ),
        None,
    ));
    let auth_token_cache = Arc::new(common_cache::ReadThroughCacheWithMetrics::new(
        auth_token_inner,
        "auth",
        "token",
        &[],
    ));
    tracing::info!("Created auth token read-through cache (no negative cache)");

    if *config.skip_writes {
        tracing::warn!(
            "SKIP_WRITES is enabled: all writes to PostgreSQL and Redis are disabled. \
             This instance is running in read-only mode for safe performance testing."
        );
    }

    // Warn about deprecated environment variables
    if std::env::var("TEAM_CACHE_TTL_SECONDS").is_ok() {
        tracing::warn!(
            "TEAM_CACHE_TTL_SECONDS is deprecated and ignored. \
             Team cache TTL is now managed by Django's HyperCache."
        );
    }
    if std::env::var("FLAGS_CACHE_TTL_SECONDS").is_ok() {
        tracing::warn!(
            "FLAGS_CACHE_TTL_SECONDS is deprecated and ignored. \
             Flags cache TTL is now managed by Django's HyperCache."
        );
    }

    let service_mode = config.service_mode.clone();

    // Spawn monitor tasks only after all fallible init succeeds. If an early return
    // fired above, the manager has already seen the real `Failure` reason and the
    // unstarted monitors are pre-completed.
    let LifecycleHandles {
        http: http_handle,
        db_monitor: db_monitor_handle,
        cohort_cache_monitor: cohort_cache_monitor_handle,
        flag_defs_cache_monitor: flag_defs_cache_monitor_handle,
        tokio_monitor: tokio_monitor_handle,
        readiness,
        liveness,
    } = handles;

    let db_monitor = DatabasePoolMonitor::new(database_pools.clone(), &config);
    tokio::spawn(async move {
        db_monitor.start_monitoring(db_monitor_handle).await;
    });

    let cohort_cache_clone = cohort_cache.clone();
    let cohort_cache_monitor_interval = config.cohort_cache_monitor_interval_secs;
    tokio::spawn(async move {
        cohort_cache_clone
            .start_monitoring(cohort_cache_monitor_interval, cohort_cache_monitor_handle)
            .await;
    });

    let flag_defs_cache_clone = flag_definitions_cache.clone();
    let flag_defs_cache_monitor_interval = config.flag_definitions_cache_monitor_interval_secs;
    tokio::spawn(async move {
        flag_defs_cache_clone
            .start_monitoring(
                flag_defs_cache_monitor_interval,
                flag_defs_cache_monitor_handle,
            )
            .await;
    });

    let tokio_monitor = TokioRuntimeMonitor::new(&tokio::runtime::Handle::current());
    tokio::spawn(async move {
        tokio_monitor.start_monitoring(tokio_monitor_handle).await;
    });

    let billing_aggregator: Option<Arc<BillingAggregator>> = if *config.billing_aggregator_enabled {
        Some(BillingAggregator::start(
            redis_client.clone(),
            BillingAggregatorConfig {
                flush_interval: Duration::from_millis(config.billing_flush_interval_ms),
                max_pending_entries: config.billing_max_pending_entries,
                per_flush_batch_size: config.billing_per_flush_batch_size,
                shutdown_flush_timeout: Duration::from_millis(
                    config.billing_shutdown_flush_timeout_ms,
                ),
            },
        ))
    } else {
        None
    };

    let app = router::router(
        redis_client,
        dedicated_redis_client,
        database_pools,
        cohort_cache,
        group_type_cache,
        geoip_service,
        readiness,
        liveness,
        feature_flags_billing_limiter,
        session_replay_billing_limiter,
        cookieless_manager,
        flags_hypercache_reader,
        flag_definitions_cache,
        flags_with_cohorts_hypercache_reader,
        team_hypercache_reader,
        config_hypercache_reader,
        rayon_dispatcher,
        team_negative_cache,
        auth_token_cache,
        cohort_membership_provider,
        billing_aggregator.clone(),
        config,
    );

    tracing::info!(
        service_mode = ?service_mode,
        "listening on {:?}",
        listener.local_addr().unwrap()
    );

    // Always signal HTTP completion (success or failure) so the manager's
    // background monitor can complete shutdown. Skipping either arm would wedge
    // `monitor_guard.wait()` in the caller.
    let serve_result = axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(http_handle.shutdown_signal())
    .await;

    // Must run *after* `axum::serve(...).await` resolves so axum has drained
    // in-flight requests; flushing earlier would miss late-arriving records.
    if let Some(ref aggregator) = billing_aggregator {
        aggregator.shutdown().await;
    }

    match serve_result {
        Ok(()) => http_handle.work_completed(),
        Err(e) => {
            tracing::error!("HTTP server error: {e}");
            http_handle.signal_failure(e.to_string());
            // Mark completed so HandleInner::Drop emits WorkCompleted instead of
            // racing the manager's processing of the Failure event and emitting
            // a duplicate Died (which oncall would read as a second failure).
            http_handle.work_completed();
        }
    }
}

/// Create a ReadWriteClient that automatically routes reads to replica and writes to primary
///
/// Returns None and logs error if client creation fails after all retries
async fn create_readwrite_client(
    writer_url: &str,
    reader_url: &str,
    client_type: &str,
    compression_config: CompressionConfig,
    response_timeout_ms: u64,
    connection_timeout_ms: u64,
    retry_count: u32,
) -> Option<Arc<dyn Client + Send + Sync>> {
    let rw_config = ReadWriteClientConfig::new(
        writer_url.to_string(),
        reader_url.to_string(),
        compression_config,
        common_redis::RedisValueFormat::default(),
        if response_timeout_ms == 0 {
            None
        } else {
            Some(Duration::from_millis(response_timeout_ms))
        },
        if connection_timeout_ms == 0 {
            None
        } else {
            Some(Duration::from_millis(connection_timeout_ms))
        },
    );

    // Use exponential backoff with jitter: 100ms, 200ms, 400ms, etc.
    let retry_strategy = ExponentialBackoff::from_millis(100)
        .map(jitter)
        .take(retry_count as usize);

    let client_type_owned = client_type.to_string();

    let result = Retry::spawn(retry_strategy, || async {
        match ReadWriteClient::with_config(rw_config.clone()).await {
            Ok(client) => Ok(Ok(client)),
            Err(e) => {
                if e.is_unrecoverable_error() {
                    tracing::error!(
                        "Permanent error creating {} ReadWriteClient: {}",
                        client_type_owned,
                        e
                    );
                    Ok(Err(e))
                } else {
                    tracing::debug!(
                        "Transient error creating {} ReadWriteClient, will retry: {}",
                        client_type_owned,
                        e
                    );
                    Err(e)
                }
            }
        }
    })
    .await;

    match result {
        Ok(Ok(client)) => {
            tracing::info!(
                "Created {} ReadWriteClient (writer: {}, reader: {})",
                client_type,
                writer_url,
                reader_url
            );
            Some(Arc::new(client))
        }
        Ok(Err(_)) => None,
        Err(e) => {
            tracing::error!(
                "Failed to create {} ReadWriteClient after {} retries: {}",
                client_type_owned,
                retry_count,
                e
            );
            None
        }
    }
}

/// Create dedicated ReadWriteClient for flags cache with graceful fallback
///
/// Implements fallback strategy:
/// 1. FLAGS_REDIS_READER_URL is not set → use FLAGS_REDIS_URL for both reads and writes
/// 2. FLAGS_REDIS_URL is not set → return None (use shared Redis)
///
/// Returns: Optional ReadWriteClient
async fn create_dedicated_readwrite_client(
    config: &Config,
    compression_config: CompressionConfig,
) -> Option<Arc<dyn Client + Send + Sync>> {
    let writer_url = config.get_flags_redis_writer_url();
    let reader_url = config.get_flags_redis_reader_url();

    match (writer_url, reader_url) {
        (Some(w_url), Some(r_url)) => {
            tracing::info!(
                "Creating dedicated flags ReadWriteClient with separate reader endpoint"
            );
            create_readwrite_client(
                w_url,
                r_url,
                "dedicated flags",
                compression_config,
                config.redis_response_timeout_ms,
                config.redis_connection_timeout_ms,
                config.redis_client_retry_count,
            )
            .await
        }
        (Some(w_url), None) => {
            tracing::info!("Creating dedicated flags ReadWriteClient using writer URL for both reads and writes");
            create_readwrite_client(
                w_url,
                w_url,
                "dedicated flags",
                compression_config,
                config.redis_response_timeout_ms,
                config.redis_connection_timeout_ms,
                config.redis_client_retry_count,
            )
            .await
        }
        (None, Some(_)) => {
            tracing::warn!(
                "FLAGS_REDIS_READER_URL set but FLAGS_REDIS_URL not set. \
                 Cannot use reader without writer. Falling back to shared Redis."
            );
            None
        }
        (None, None) => {
            tracing::info!(
                "Using shared Redis for flags cache (no dedicated flags Redis configured)"
            );
            None
        }
    }
}

/// Helper to create a Redis client with error logging and retry logic
/// Returns None and logs an error if client creation fails after all retries
///
/// Retry behavior:
/// - Delegates to redis crate's `is_unrecoverable_error()` for error classification
/// - Overrides: InvalidClientConfig and AuthenticationFailed always treated as permanent (no retry)
/// - In practice, most connection errors (DNS, connection refused) are also permanent
/// - Uses exponential backoff with jitter when retrying transient errors
pub async fn create_redis_client(
    url: &str,
    client_type: &str,
    compression_config: CompressionConfig,
    response_timeout_ms: u64,
    connection_timeout_ms: u64,
    retry_count: u32,
) -> Option<Arc<RedisClient>> {
    // Use exponential backoff with jitter: 100ms, 200ms, 400ms, etc.
    // When retry_count=0, .take(0) means no retries (only initial attempt)
    let retry_strategy = ExponentialBackoff::from_millis(100)
        .map(jitter)
        .take(retry_count as usize);

    let url_owned = url.to_string();
    let client_type_owned = client_type.to_string();

    let result = Retry::spawn(retry_strategy, || async {
        match RedisClient::with_config(
            url_owned.clone(),
            compression_config.clone(),
            common_redis::RedisValueFormat::default(),
            if response_timeout_ms == 0 {
                None
            } else {
                Some(Duration::from_millis(response_timeout_ms))
            },
            if connection_timeout_ms == 0 {
                None
            } else {
                Some(Duration::from_millis(connection_timeout_ms))
            },
        )
        .await
        {
            Ok(client) => Ok(Ok(client)),
            Err(e) => {
                if e.is_unrecoverable_error() {
                    tracing::error!(
                        "Permanent error creating {} Redis client for URL {}: {}",
                        client_type_owned,
                        url_owned,
                        e
                    );
                    // Return Ok(Err) to stop retrying but signal error
                    Ok(Err(e))
                } else {
                    tracing::debug!(
                        "Transient error creating {} Redis client, will retry: {}",
                        client_type_owned,
                        e
                    );
                    Err(e)
                }
            }
        }
    })
    .await;

    // Use nested Result to distinguish:
    // - Ok(Ok(client)): successful connection
    // - Ok(Err(e)): permanent error, don't retry
    // - Err(e): retryable error that will trigger retry logic
    match result {
        Ok(Ok(client)) => Some(Arc::new(client)),
        Ok(Err(_)) => {
            // Permanent error - already logged above
            None
        }
        Err(e) => {
            tracing::error!(
                "Failed to create {} Redis client for URL {} after {} retries: {}",
                client_type_owned,
                url_owned,
                retry_count,
                e
            );
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lifecycle::LifecycleError;

    /// Locks in the contract that drives the early-return paths in `serve()`:
    /// `fail_init` must surface a `ComponentFailure { tag: "http-server", reason }` —
    /// not a misleading `ComponentDied { tag: "http-server" }` from the http handle's
    /// drop, which is the easy regression mode if a future component is added to
    /// `LifecycleHandles` without being wired into `fail_init`.
    #[tokio::test]
    async fn fail_init_reports_failure_not_died() {
        let mut manager = Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_global_shutdown_timeout(Duration::from_secs(5))
            .build();
        let handles = register_components(&mut manager);
        let guard = manager.monitor_background();

        handles.fail_init("redis init failed");
        drop(handles);

        let result = tokio::time::timeout(Duration::from_secs(3), guard.wait())
            .await
            .expect("monitor did not finish within timeout");
        assert!(
            matches!(
                &result,
                Err(LifecycleError::ComponentFailure { tag, reason })
                    if tag == "http-server" && reason == "redis init failed"
            ),
            "expected ComponentFailure {{ tag: \"http-server\", reason: \"redis init failed\" }}, got {result:?}"
        );
    }

    #[tokio::test]
    async fn test_create_dedicated_readwrite_client_no_config() {
        // When FLAGS_REDIS_URL is not set, should return None
        let config = Config {
            flags_redis_url: "".to_string(),
            flags_redis_reader_url: "".to_string(),
            redis_client_retry_count: 0,
            ..Config::default_test_config()
        };

        let compression_config = CompressionConfig::disabled();
        let client = create_dedicated_readwrite_client(&config, compression_config).await;

        assert!(client.is_none());
    }

    #[tokio::test]
    async fn test_create_dedicated_readwrite_client_with_invalid_url() {
        // When FLAGS_REDIS_URL is set but unreachable, should return None
        let config = Config {
            flags_redis_url: "redis://invalid-host:6379/".to_string(),
            flags_redis_reader_url: "".to_string(),
            redis_client_retry_count: 0, // No retries for fast test
            ..Config::default_test_config()
        };

        let compression_config = CompressionConfig::disabled();
        let client = create_dedicated_readwrite_client(&config, compression_config).await;

        assert!(client.is_none());
    }

    #[tokio::test]
    async fn test_create_dedicated_readwrite_client_reader_without_writer() {
        // When only FLAGS_REDIS_READER_URL is set (misconfiguration), should return None
        let config = Config {
            flags_redis_url: "".to_string(),
            flags_redis_reader_url: "redis://localhost:6379/".to_string(),
            redis_client_retry_count: 0,
            ..Config::default_test_config()
        };

        let compression_config = CompressionConfig::disabled();
        let client = create_dedicated_readwrite_client(&config, compression_config).await;

        assert!(client.is_none());
    }

    #[tokio::test]
    async fn test_redis_error_types() {
        use common_redis::RedisClient;

        let test_cases = vec![
            ("absolutegarbage", "Garbage URL"),
            ("wrong-protocol://localhost:6379", "Wrong protocol"),
            ("redis://localhost:6378", "Wrong port (connection refused)"),
        ];

        for (url, description) in test_cases {
            println!("\n--- Testing: {description} ---");
            println!("URL: {url}");

            let result = RedisClient::with_config(
                url.to_string(),
                CompressionConfig::disabled(),
                common_redis::RedisValueFormat::default(),
                Some(Duration::from_millis(100)),
                Some(Duration::from_millis(5000)),
            )
            .await;

            match result {
                Ok(_) => println!("✅ Success (unexpected!)"),
                Err(e) => {
                    println!("❌ Error type: {e:?}");
                    println!("   Error message: {e}");
                    println!("   Is recoverable: {}", !e.is_unrecoverable_error());
                }
            }
        }
    }
}
