use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use common_database::get_pool;
use common_geoip::GeoIpClient;
use common_redis::RedisClient;
use health::{HealthHandle, HealthRegistry};
use limiters::redis::QUOTA_LIMITER_CACHE_KEY;
use tokio::net::TcpListener;

use crate::billing_limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::config::Config;
use crate::db_monitor::DatabasePoolMonitor;
use crate::router;
use common_cookieless::CookielessManager;

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    // Create separate Redis clients for reading and writing
    // NB: if either of these URLs don't exist in the config, we default to the writer
    let redis_reader_client =
        match RedisClient::new(config.get_redis_reader_url().to_string()).await {
            Ok(client) => Arc::new(client),
            Err(e) => {
                tracing::error!(
                    "Failed to create Redis reader client for URL {}: {}",
                    config.get_redis_reader_url(),
                    e
                );
                return;
            }
        };

    let redis_writer_client =
        match RedisClient::new(config.get_redis_writer_url().to_string()).await {
            Ok(client) => Arc::new(client),
            Err(e) => {
                tracing::error!(
                    "Failed to create Redis writer client for URL {}: {}",
                    config.get_redis_writer_url(),
                    e
                );
                return;
            }
        };

    let reader = match get_pool(&config.read_database_url, config.max_pg_connections).await {
        Ok(client) => {
            tracing::info!("Successfully created read Postgres client");
            Arc::new(client)
        }
        Err(e) => {
            tracing::error!(
                error = %e,
                url = %config.read_database_url,
                max_connections = config.max_pg_connections,
                "Failed to create read Postgres client"
            );
            return;
        }
    };

    let writer =
        // TODO - we should have a dedicated URL for both this and the reader – the reader will read
        // from the replica, and the writer will write to the main database.
        match get_pool(&config.write_database_url, config.max_pg_connections).await {
            Ok(client) => {
                tracing::info!("Successfully created write Postgres client");
                Arc::new(client)
            }
            Err(e) => {
                tracing::error!(
                    error = %e,
                    url = %config.write_database_url,
                    max_connections = config.max_pg_connections,
                    "Failed to create write Postgres client"
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
        reader.clone(),
        Some(config.cache_max_cohort_entries),
        Some(config.cache_ttl_seconds),
    ));

    let health = HealthRegistry::new("liveness");

    // TODO - we don't have a more complex health check yet, but we should add e.g. some around DB operations
    let simple_loop = health
        .register("simple_loop".to_string(), Duration::from_secs(30))
        .await;
    tokio::spawn(liveness_loop(simple_loop));

    // Start database pool monitoring
    let db_monitor = DatabasePoolMonitor::new(reader.clone(), writer.clone());
    tokio::spawn(async move {
        db_monitor.start_monitoring().await;
    });

    let feature_flags_billing_limiter = match FeatureFlagsLimiter::new(
        Duration::from_secs(5),
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
        Duration::from_secs(5),
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

    let cookieless_manager = Arc::new(CookielessManager::new(
        config.get_cookieless_config(),
        redis_reader_client.clone(), // NB: the cookieless manager only reads from redis, so it's safe to just use the reader client
    ));

    let app = router::router(
        redis_reader_client,
        redis_writer_client,
        reader,
        writer,
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
