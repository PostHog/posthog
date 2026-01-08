use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use common_geoip::GeoIpClient;
use common_hypercache::{HyperCacheConfig, HyperCacheReader};
use common_redis::{
    Client, CompressionConfig, ReadWriteClient, ReadWriteClientConfig, RedisClient,
};
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
        Some(config.cohort_cache_capacity_bytes),
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

    // Start cohort cache monitoring
    let cohort_cache_clone = cohort_cache.clone();
    let cohort_cache_monitor_interval = config.cohort_cache_monitor_interval_secs;
    tokio::spawn(async move {
        cohort_cache_clone
            .start_monitoring(cohort_cache_monitor_interval)
            .await;
    });

    let feature_flags_billing_limiter = match FeatureFlagsLimiter::new(
        Duration::from_secs(config.billing_limiter_cache_ttl_secs),
        redis_client.clone(), // Limiter only reads from redis, ReadWriteClient automatically routes reads to replica
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
        redis_client.clone(), // Limiter only reads from redis, ReadWriteClient automatically routes reads to replica
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
        config.redis_response_timeout_ms,
        config.redis_connection_timeout_ms,
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

    // Create HyperCacheReader for feature flags at startup
    // This avoids per-request AWS SDK initialization overhead
    let flags_redis_client = dedicated_redis_client
        .clone()
        .unwrap_or_else(|| redis_client.clone());

    let mut hypercache_config = HyperCacheConfig::new(
        "feature_flags".to_string(),
        "flags.json".to_string(),
        config.object_storage_region.clone(),
        config.object_storage_bucket.clone(),
    );

    if !config.object_storage_endpoint.is_empty() {
        hypercache_config.s3_endpoint = Some(config.object_storage_endpoint.clone());
    }

    let flags_hypercache_reader =
        match HyperCacheReader::new(flags_redis_client, hypercache_config).await {
            Ok(reader) => {
                tracing::info!("Created HyperCacheReader for feature flags");
                Arc::new(reader)
            }
            Err(e) => {
                tracing::error!("Failed to create HyperCacheReader: {:?}", e);
                return;
            }
        };

    let app = router::router(
        redis_client,
        dedicated_redis_client,
        database_pools,
        cohort_cache,
        geoip_service,
        health,
        feature_flags_billing_limiter,
        session_replay_billing_limiter,
        cookieless_manager,
        flags_hypercache_reader,
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
async fn create_redis_client(
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
