use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use common_geoip::GeoIpClient;
use common_redis::{CompressionConfig, RedisClient};
use health::{HealthHandle, HealthRegistry};
use limiters::redis::QUOTA_LIMITER_CACHE_KEY;
use tokio::net::TcpListener;

use crate::billing_limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::config::Config;
use crate::database_pools::DatabasePools;
use crate::db_monitor::DatabasePoolMonitor;
use crate::router;
use common_cookieless::CookielessManager;

/// Helper to create a Redis client with error logging
/// Returns None and logs an error if client creation fails
async fn create_redis_client(
    url: &str,
    client_type: &str,
    compression_config: CompressionConfig,
) -> Option<Arc<RedisClient>> {
    match RedisClient::with_config(
        url.to_string(),
        compression_config,
        common_redis::RedisValueFormat::default(),
    )
    .await
    {
        Ok(client) => Some(Arc::new(client)),
        Err(e) => {
            tracing::error!(
                "Failed to create {} Redis client for URL {}: {}",
                client_type,
                url,
                e
            );
            None
        }
    }
}

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    // Configure compression based on environment variable
    let compression_config = if *config.redis_compression_enabled {
        tracing::info!("Redis compression enabled");
        CompressionConfig::default()
    } else {
        tracing::info!("Redis compression disabled");
        CompressionConfig::disabled()
    };

    // Create separate Redis clients for shared Redis (non-critical path: analytics, billing, cookieless)
    let Some(redis_reader_client) = create_redis_client(
        config.get_redis_reader_url(),
        "shared reader",
        compression_config.clone(),
    )
    .await
    else {
        return;
    };

    let Some(redis_writer_client) = create_redis_client(
        config.get_redis_writer_url(),
        "shared writer",
        compression_config.clone(),
    )
    .await
    else {
        return;
    };

    // Create dedicated Redis clients for flags cache (critical path isolation)
    // Only create separate clients if dedicated flags Redis URLs are configured
    let (dedicated_redis_reader_client, dedicated_redis_writer_client) = match (
        config.get_flags_redis_reader_url(),
        config.get_flags_redis_writer_url(),
    ) {
        (Some(reader_url), Some(writer_url)) => {
            // Dedicated flags Redis is configured
            let Some(reader) = create_redis_client(
                reader_url,
                "dedicated flags reader",
                compression_config.clone(),
            )
            .await
            else {
                return;
            };

            let Some(writer) = create_redis_client(
                writer_url,
                "dedicated flags writer",
                compression_config.clone(),
            )
            .await
            else {
                return;
            };

            tracing::info!("Dedicated flags Redis configured");
            (Some(reader), Some(writer))
        }
        (Some(_), None) | (None, Some(_)) => {
            tracing::warn!(
                "Incomplete flags Redis configuration: both reader and writer URLs must be set. Falling back to shared Redis (Mode 1)."
            );
            (None, None)
        }
        _ => {
            tracing::info!(
                "Using shared Redis for flags cache (no dedicated flags Redis configured)"
            );
            (None, None)
        }
    };

    // Log the cache migration mode based on configuration
    let cache_mode = match (
        dedicated_redis_reader_client.is_some(),
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
            return;
        }
    };

    let cohort_cache = Arc::new(CohortCacheManager::new(
        database_pools.non_persons_reader.clone(),
        Some(config.cache_max_cohort_entries),
        Some(config.cache_ttl_seconds),
    ));

    let health = HealthRegistry::new("liveness");

    // Liveness checks only verify the process is alive (simple heartbeat loop).
    // Readiness checks (in router.rs) verify DB connectivity before accepting traffic.
    let simple_loop = health
        .register(
            "simple_loop".to_string(),
            Duration::from_secs(config.health_check_interval_secs),
        )
        .await;
    tokio::spawn(liveness_loop(simple_loop));

    // Start database pool monitoring
    let db_monitor = DatabasePoolMonitor::new(database_pools.clone(), &config);
    tokio::spawn(async move {
        db_monitor.start_monitoring().await;
    });

    let feature_flags_billing_limiter = match FeatureFlagsLimiter::new(
        Duration::from_secs(config.billing_limiter_cache_ttl_secs),
        redis_reader_client.clone(), // NB: the limiter only reads from redis, so it's safe to just use the reader client
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
    ) {
        Ok(limiter) => limiter,
        Err(e) => {
            tracing::error!("Failed to create feature flags billing limiter: {}", e);
            return;
        }
    };

    let session_replay_billing_limiter = match SessionReplayLimiter::new(
        Duration::from_secs(config.billing_limiter_cache_ttl_secs),
        redis_reader_client.clone(), // NB: the limiter only reads from redis, so it's safe to just use the reader client
        QUOTA_LIMITER_CACHE_KEY.to_string(),
        None,
    ) {
        Ok(limiter) => limiter,
        Err(e) => {
            tracing::error!("Failed to create session replay billing limiter: {}", e);
            return;
        }
    };

    let redis_cookieless_client = match RedisClient::with_config(
        config.get_redis_cookieless_url().to_string(),
        compression_config.clone(),
        common_redis::RedisValueFormat::default(),
    )
    .await
    {
        Ok(client) => Arc::new(client),
        Err(e) => {
            tracing::error!(
                "Failed to create Redis cookieless client for URL {}: {}",
                config.get_redis_cookieless_url(),
                e
            );
            return;
        }
    };

    let cookieless_manager = Arc::new(CookielessManager::new(
        config.get_cookieless_config(),
        redis_cookieless_client.clone(),
    ));

    let app = router::router(
        redis_reader_client,
        redis_writer_client,
        dedicated_redis_reader_client,
        dedicated_redis_writer_client,
        database_pools,
        cohort_cache,
        geoip_service,
        health,
        feature_flags_billing_limiter,
        session_replay_billing_limiter,
        cookieless_manager,
        config,
    );

    tracing::info!("listening on {:?}", listener.local_addr().unwrap());
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown)
    .await
    .unwrap()
}

async fn liveness_loop(handle: HealthHandle) {
    loop {
        handle.report_healthy().await;
        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
    }
}
