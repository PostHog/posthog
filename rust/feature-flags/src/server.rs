use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use common_geoip::GeoIpClient;
use common_redis::{CompressionConfig, RedisClient};
use health::{HealthHandle, HealthRegistry};
use limiters::redis::QUOTA_LIMITER_CACHE_KEY;
use tokio::net::TcpListener;
use tokio_retry::strategy::{jitter, ExponentialBackoff};
use tokio_retry::Retry;

use crate::billing_limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::config::Config;
use crate::database_pools::DatabasePools;
use crate::db_monitor::DatabasePoolMonitor;
use crate::router;
use common_cookieless::CookielessManager;

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
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

    // Create separate Redis clients for shared Redis (non-critical path: analytics, billing, cookieless)
    // "shared" means the Redis client shares the cache with the Dango PostHog web app.
    let Some(redis_reader_client) = create_redis_client(
        config.get_redis_reader_url(),
        "shared reader",
        compression_config.clone(),
        config.redis_client_retry_count,
    )
    .await
    else {
        return;
    };

    let Some(redis_writer_client) = create_redis_client(
        config.get_redis_writer_url(),
        "shared writer",
        compression_config.clone(),
        config.redis_client_retry_count,
    )
    .await
    else {
        return;
    };

    // Create dedicated Redis clients for flags cache (critical path isolation)
    let (dedicated_redis_reader_client, dedicated_redis_writer_client) =
        create_dedicated_redis_clients(&config, compression_config.clone()).await;

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

    let Some(redis_cookieless_client) = create_redis_client(
        &config.get_redis_cookieless_url(),
        "cookieless",
        compression_config.clone(),
        config.redis_client_retry_count,
    )
    .await
    else {
        return;
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

/// Create dedicated Redis clients for flags cache with graceful fallback
///
/// Implements fallback strategy:
/// 1. FLAGS_REDIS_READER_URL fails or is not set → use FLAGS_REDIS_URL for reads
/// 2. FLAGS_REDIS_URL fails or is not set → return None (use shared Redis)
///
/// Returns: (reader_client, writer_client)
async fn create_dedicated_redis_clients(
    config: &Config,
    compression_config: CompressionConfig,
) -> (Option<Arc<RedisClient>>, Option<Arc<RedisClient>>) {
    let writer_url = config.get_flags_redis_writer_url();
    let reader_url = config.get_flags_redis_reader_url();

    // Try to create writer client
    let writer = if let Some(url) = writer_url {
        create_redis_client(
            url,
            "dedicated flags writer",
            compression_config.clone(),
            config.redis_client_retry_count,
        )
        .await
    } else {
        None
    };

    // Try to create reader client independently (don't depend on writer success)
    let reader = if let Some(url) = reader_url {
        create_redis_client(
            url,
            "dedicated flags reader",
            compression_config.clone(),
            config.redis_client_retry_count,
        )
        .await
    } else {
        None
    };

    // Determine final configuration with fallback logic
    match (reader, writer) {
        (Some(r), Some(w)) => {
            tracing::info!("Dedicated flags Redis configured with separate reader endpoint");
            (Some(r), Some(w))
        }
        (None, Some(w)) => {
            if reader_url.is_some() {
                tracing::warn!(
                    "FLAGS_REDIS_READER_URL connection failed, falling back to FLAGS_REDIS_URL for reads"
                );
            }
            (Some(w.clone()), Some(w))
        }
        (Some(_), None) => {
            // Reader succeeded but writer failed - can't use reader without writer
            tracing::warn!(
                "FLAGS_REDIS_URL connection failed but FLAGS_REDIS_READER_URL succeeded. \
                 Cannot use reader without writer. Falling back to shared Redis."
            );
            (None, None)
        }
        (None, None) => {
            if writer_url.is_some() || reader_url.is_some() {
                tracing::warn!(
                    "Both dedicated flags Redis connections failed falling back to shared Redis"
                );
            } else {
                tracing::info!(
                    "Using shared Redis for flags cache (no dedicated flags Redis configured)"
                );
            }
            (None, None)
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
async fn create_redis_client(
    url: &str,
    client_type: &str,
    compression_config: CompressionConfig,
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

async fn liveness_loop(handle: HealthHandle) {
    loop {
        handle.report_healthy().await;
        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_create_dedicated_redis_clients_no_config() {
        // When FLAGS_REDIS_URL is not set, should return (None, None)
        let config = Config {
            flags_redis_url: "".to_string(),
            flags_redis_reader_url: "".to_string(),
            redis_client_retry_count: 0,
            ..Config::default_test_config()
        };

        let compression_config = CompressionConfig::disabled();
        let (reader, writer) = create_dedicated_redis_clients(&config, compression_config).await;

        assert!(reader.is_none());
        assert!(writer.is_none());
    }

    #[tokio::test]
    async fn test_create_dedicated_redis_clients_with_invalid_url() {
        // When FLAGS_REDIS_URL is set but unreachable, should return (None, None)
        let config = Config {
            flags_redis_url: "redis://invalid-host:6379/".to_string(),
            flags_redis_reader_url: "".to_string(),
            redis_client_retry_count: 0, // No retries for fast test
            ..Config::default_test_config()
        };

        let compression_config = CompressionConfig::disabled();
        let (reader, writer) = create_dedicated_redis_clients(&config, compression_config).await;

        assert!(reader.is_none());
        assert!(writer.is_none());
    }

    #[tokio::test]
    async fn test_create_dedicated_redis_clients_reader_without_writer() {
        // When only FLAGS_REDIS_READER_URL is set (misconfiguration), should return (None, None)
        let config = Config {
            flags_redis_url: "".to_string(),
            flags_redis_reader_url: "redis://localhost:6379/".to_string(),
            redis_client_retry_count: 0,
            ..Config::default_test_config()
        };

        let compression_config = CompressionConfig::disabled();
        let (reader, writer) = create_dedicated_redis_clients(&config, compression_config).await;

        assert!(reader.is_none());
        assert!(writer.is_none());
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
