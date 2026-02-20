use std::{
    future::ready,
    panic::{catch_unwind, AssertUnwindSafe},
    sync::Arc,
    time::Duration,
};

use crate::billing_limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
use crate::database_pools::DatabasePools;
use axum::{
    http::{Method, StatusCode},
    routing::{any, get},
    Router,
};
use common_cookieless::CookielessManager;
use common_geoip::GeoIpClient;
use common_hypercache::HyperCacheReader;
use common_metrics::{setup_metrics_recorder, track_metrics};
use common_redis::Client as RedisClient;
use health::HealthRegistry;
use metrics::gauge;
use sqlx::PgPool;
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{
    cors::{AllowHeaders, AllowOrigin, CorsLayer},
    trace::TraceLayer,
};

use crate::{
    api::{
        endpoint, flag_definitions,
        flag_definitions_rate_limiter::FlagDefinitionsRateLimiter,
        flags_rate_limiter::{FlagsRateLimiter, IpRateLimiter},
    },
    cohorts::cohort_cache_manager::CohortCacheManager,
    config::{Config, TeamIdCollection},
    metrics::{
        consts::{FLAG_DEFINITIONS_RATE_LIMITED_COUNTER, FLAG_DEFINITIONS_REQUESTS_COUNTER},
        utils::team_id_label_filter,
    },
};

#[derive(Clone)]
pub struct State {
    // Shared Redis for non-critical path (analytics counters, billing limits)
    // ReadWriteClient automatically routes reads to replica and writes to primary
    pub redis_client: Arc<dyn RedisClient + Send + Sync>,
    // Dedicated Redis for flags cache (critical path isolation)
    // None if not configured (falls back to shared Redis)
    // ReadWriteClient automatically routes reads to replica and writes to primary
    pub dedicated_redis_client: Option<Arc<dyn RedisClient + Send + Sync>>,
    pub database_pools: Arc<DatabasePools>,
    pub cohort_cache_manager: Arc<CohortCacheManager>,
    pub geoip: Arc<GeoIpClient>,
    pub team_ids_to_track: TeamIdCollection,
    pub feature_flags_billing_limiter: FeatureFlagsLimiter,
    pub session_replay_billing_limiter: SessionReplayLimiter,
    pub cookieless_manager: Arc<CookielessManager>,
    pub flag_definitions_limiter: FlagDefinitionsRateLimiter,
    pub config: Config,
    pub flags_rate_limiter: FlagsRateLimiter,
    pub ip_rate_limiter: IpRateLimiter,
    /// Pre-initialized HyperCacheReader for feature flags (flags.json)
    /// Initialized once at startup to avoid per-request AWS SDK initialization
    pub flags_hypercache_reader: Arc<HyperCacheReader>,
    /// Pre-initialized HyperCacheReader for feature flags with cohorts (flags_with_cohorts.json)
    /// Used by the /flags/definitions endpoint
    pub flags_with_cohorts_hypercache_reader: Arc<HyperCacheReader>,
    /// Pre-initialized HyperCacheReader for team metadata (full_metadata.json)
    /// Uses token-based lookup instead of team_id
    pub team_hypercache_reader: Arc<HyperCacheReader>,
    /// Pre-initialized HyperCacheReader for remote config (array/config.json)
    /// Reads pre-computed config from Python's RemoteConfig.build_config()
    /// Uses token-based lookup (api_token)
    pub config_hypercache_reader: Arc<HyperCacheReader>,
}

#[allow(clippy::too_many_arguments)]
pub fn router(
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    dedicated_redis_client: Option<Arc<dyn RedisClient + Send + Sync>>,
    database_pools: Arc<DatabasePools>,
    cohort_cache: Arc<CohortCacheManager>,
    geoip: Arc<GeoIpClient>,
    liveness: HealthRegistry,
    feature_flags_billing_limiter: FeatureFlagsLimiter,
    session_replay_billing_limiter: SessionReplayLimiter,
    cookieless_manager: Arc<CookielessManager>,
    flags_hypercache_reader: Arc<HyperCacheReader>,
    flags_with_cohorts_hypercache_reader: Arc<HyperCacheReader>,
    team_hypercache_reader: Arc<HyperCacheReader>,
    config_hypercache_reader: Arc<HyperCacheReader>,
    config: Config,
) -> Router {
    // Initialize flag definitions rate limiter with default and custom team rates
    let flag_definitions_limiter = FlagDefinitionsRateLimiter::new(
        config.flag_definitions_default_rate_per_minute,
        config.flag_definitions_rate_limits.0.clone(),
        FLAG_DEFINITIONS_REQUESTS_COUNTER,
        FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
    )
    .expect("Failed to initialize flag definitions rate limiter");

    // Initialize token-based rate limiter with configuration
    let flags_rate_limiter = FlagsRateLimiter::new(
        *config.flags_rate_limit_enabled,
        *config.flags_rate_limit_log_only,
        config.flags_bucket_replenish_rate,
        config.flags_bucket_capacity,
    )
    .unwrap_or_else(|e| {
        panic!(
            "Invalid token-based rate limit configuration: {e}. \
             Check FLAGS_BUCKET_REPLENISH_RATE (must be > 0) and FLAGS_BUCKET_CAPACITY (must be > 0)"
        )
    });

    // Initialize IP-based rate limiter with configuration
    let ip_rate_limiter = IpRateLimiter::new(
        *config.flags_ip_rate_limit_enabled,
        *config.flags_ip_rate_limit_log_only,
        config.flags_ip_replenish_rate,
        config.flags_ip_burst_size,
    )
    .unwrap_or_else(|e| {
        panic!(
            "Invalid IP-based rate limit configuration: {e}. \
             Check FLAGS_IP_REPLENISH_RATE (must be > 0) and FLAGS_IP_BURST_SIZE (must be > 0)"
        )
    });

    // Clone database_pools for readiness check before moving into State
    let db_pools_for_readiness = database_pools.clone();

    spawn_rate_limiter_cleanup_task(
        flags_rate_limiter.clone(),
        ip_rate_limiter.clone(),
        flag_definitions_limiter.clone(),
        config.rate_limiter_cleanup_interval_secs,
    );

    let state = State {
        redis_client,
        dedicated_redis_client,
        database_pools,
        cohort_cache_manager: cohort_cache,
        geoip,
        team_ids_to_track: config.team_ids_to_track.clone(),
        feature_flags_billing_limiter,
        session_replay_billing_limiter,
        cookieless_manager,
        flag_definitions_limiter,
        config: config.clone(),
        flags_rate_limiter,
        ip_rate_limiter,
        flags_hypercache_reader,
        flags_with_cohorts_hypercache_reader,
        team_hypercache_reader,
        config_hypercache_reader,
    };

    // Very permissive CORS policy, as old SDK versions
    // and reverse proxies might send funky headers.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS, Method::HEAD])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    // Clone database_pools for the startup route
    let db_pools_for_startup = state.database_pools.clone();

    // liveness/readiness/startup checks
    let status_router = Router::new()
        .route("/", get(index))
        .route(
            "/_readiness",
            get(move || readiness(db_pools_for_readiness.clone())),
        )
        .route("/_liveness", get(move || ready(liveness.get_status())))
        .route(
            "/_startup",
            get(move || startup(db_pools_for_startup.clone())),
        );

    // flags endpoint
    // IP rate limiting is now handled in the endpoint handler for better control and log-only mode support
    let flags_router = Router::new()
        .route("/flags", any(endpoint::flags))
        .route("/flags/", any(endpoint::flags))
        .route(
            "/flags/definitions",
            any(flag_definitions::flags_definitions),
        )
        .route(
            "/flags/definitions/",
            any(flag_definitions::flags_definitions),
        )
        .route("/decide", any(endpoint::flags))
        .route("/decide/", any(endpoint::flags))
        .layer(ConcurrencyLimitLayer::new(config.max_concurrency));

    let router = Router::new()
        .merge(status_router)
        .merge(flags_router)
        .layer(TraceLayer::new_for_http())
        .layer(cors)
        .layer(axum::middleware::from_fn(track_metrics))
        .with_state(state);

    // Don't install metrics unless asked to
    // Global metrics recorders can play poorly with e.g. tests
    // In other words, only turn these on in production
    if config.enable_metrics {
        common_metrics::set_label_filter(team_id_label_filter(config.team_ids_to_track.clone()));
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}

/// Spawns a background task to periodically clean up stale rate limiter entries.
/// Without this, the rate limiters would accumulate entries for every unique
/// token/IP that makes a request, leading to unbounded memory growth.
/// See: https://docs.rs/governor/latest/governor/struct.RateLimiter.html#method.retain_recent
fn spawn_rate_limiter_cleanup_task(
    flags_rate_limiter: FlagsRateLimiter,
    ip_rate_limiter: IpRateLimiter,
    flag_definitions_limiter: FlagDefinitionsRateLimiter,
    cleanup_interval_secs: u64,
) {
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(cleanup_interval_secs));
        loop {
            interval.tick().await;

            let result = catch_unwind(AssertUnwindSafe(|| {
                // Remove stale entries and reclaim memory
                flags_rate_limiter.cleanup();
                ip_rate_limiter.cleanup();
                flag_definitions_limiter.cleanup();

                // Report metrics for monitoring
                gauge!("flags_rate_limiter_token_entries").set(flags_rate_limiter.len() as f64);
                gauge!("flags_rate_limiter_ip_entries").set(ip_rate_limiter.len() as f64);
                gauge!("flags_rate_limiter_definitions_entries")
                    .set(flag_definitions_limiter.len() as f64);

                tracing::debug!(
                    token_entries = flags_rate_limiter.len(),
                    ip_entries = ip_rate_limiter.len(),
                    definitions_entries = flag_definitions_limiter.len(),
                    "Rate limiter cleanup completed"
                );
            }));

            if let Err(e) = result {
                tracing::error!(
                    ?e,
                    "Rate limiter cleanup panicked, will retry next interval"
                );
            }
        }
    });
}

/// Tests a single database pool by acquiring a connection and optionally running a test query.
///
/// When `skip_query` is true (because `test_before_acquire` is enabled), only connection
/// acquisition is tested since sqlx already validates connections on acquire.
async fn test_pool_connection(pool: &PgPool, name: &str, skip_query: bool) -> Result<(), String> {
    let mut conn = pool
        .acquire()
        .await
        .map_err(|e| format!("{name} pool unavailable: {e}"))?;

    if !skip_query {
        sqlx::query("SELECT 1")
            .execute(&mut *conn)
            .await
            .map_err(|e| format!("{name} connection test failed: {e}"))?;
    }

    Ok(())
}

pub async fn readiness(
    database_pools: Arc<DatabasePools>,
) -> Result<&'static str, (StatusCode, String)> {
    let pools = [
        ("non_persons_reader", &database_pools.non_persons_reader),
        ("non_persons_writer", &database_pools.non_persons_writer),
        ("persons_reader", &database_pools.persons_reader),
        ("persons_writer", &database_pools.persons_writer),
    ];

    for (name, pool) in pools {
        test_pool_connection(pool, name, database_pools.test_before_acquire)
            .await
            .map_err(|e| (StatusCode::SERVICE_UNAVAILABLE, e))?;
    }

    Ok("ready")
}

pub async fn index() -> &'static str {
    "feature flags"
}

/// Startup probe for Kubernetes.
///
/// Warms up database connection pools by acquiring and testing connections.
/// This ensures the first user request doesn't pay connection establishment latency.
///
/// Always returns 200 OK - warmup failures are logged but don't block startup.
/// This preserves the resilience of lazy pool initialization: if the DB is temporarily
/// unavailable at startup, the pod still starts and will connect on first request.
pub async fn startup(database_pools: Arc<DatabasePools>) -> &'static str {
    // Check if persons pools are aliased to non-persons pools
    // (this happens when persons_db_routing is disabled)
    let persons_reader_is_distinct = !Arc::ptr_eq(
        &database_pools.non_persons_reader,
        &database_pools.persons_reader,
    );
    let persons_writer_is_distinct = !Arc::ptr_eq(
        &database_pools.non_persons_writer,
        &database_pools.persons_writer,
    );

    // Best-effort warmup: try all pools in parallel, log failures, never block startup
    let skip_query = database_pools.test_before_acquire;
    let (reader_result, writer_result, persons_reader_result, persons_writer_result) = tokio::join!(
        test_pool_connection(
            &database_pools.non_persons_reader,
            "non_persons_reader",
            skip_query
        ),
        test_pool_connection(
            &database_pools.non_persons_writer,
            "non_persons_writer",
            skip_query
        ),
        async {
            if persons_reader_is_distinct {
                test_pool_connection(&database_pools.persons_reader, "persons_reader", skip_query)
                    .await
            } else {
                Ok(()) // Already warmed via non_persons_reader
            }
        },
        async {
            if persons_writer_is_distinct {
                test_pool_connection(&database_pools.persons_writer, "persons_writer", skip_query)
                    .await
            } else {
                Ok(()) // Already warmed via non_persons_writer
            }
        },
    );

    // Log results
    log_warmup_result("non_persons_reader", reader_result);
    log_warmup_result("non_persons_writer", writer_result);

    if persons_reader_is_distinct {
        log_warmup_result("persons_reader", persons_reader_result);
    } else {
        tracing::info!("persons_reader is aliased to non_persons_reader, already warmed");
    }

    if persons_writer_is_distinct {
        log_warmup_result("persons_writer", persons_writer_result);
    } else {
        tracing::info!("persons_writer is aliased to non_persons_writer, already warmed");
    }

    "started"
}

fn log_warmup_result(name: &str, result: Result<(), String>) {
    match result {
        Ok(()) => tracing::info!("{name} pool warmed up successfully"),
        Err(e) => tracing::warn!("{name} warmup failed (will connect on first use): {e}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_pool_connection_success() {
        // This test requires a running database
        let database_url = std::env::var("DATABASE_URL")
            .unwrap_or("postgres://posthog:posthog@localhost:5432/test_database".to_string());

        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect_lazy(&database_url)
            .expect("Failed to create pool");

        let result = test_pool_connection(&pool, "test_pool", false).await;

        // If database is available, connection test should succeed
        // If not, it will fail - both are acceptable in test environment
        // This test primarily verifies the function doesn't panic
        match result {
            Ok(()) => {
                // Pool connection test succeeded
            }
            Err(e) => {
                // Expected when no database is running
                assert!(e.contains("test_pool"));
            }
        }
    }

    #[tokio::test]
    async fn test_pool_connection_failure_includes_pool_name() {
        // Create a pool with an invalid connection string
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .acquire_timeout(std::time::Duration::from_millis(100))
            .connect_lazy("postgres://invalid:invalid@localhost:54321/nonexistent")
            .expect("Failed to create pool");

        let result = test_pool_connection(&pool, "test_pool", false).await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            err.contains("test_pool"),
            "Error should contain pool name: {err}"
        );
    }

    #[tokio::test]
    async fn test_startup_always_returns_started() {
        // Create pools with invalid connection strings to simulate DB unavailability
        let invalid_pool = Arc::new(
            sqlx::postgres::PgPoolOptions::new()
                .max_connections(1)
                .acquire_timeout(std::time::Duration::from_millis(100))
                .connect_lazy("postgres://invalid:invalid@localhost:54321/nonexistent")
                .expect("Failed to create pool"),
        );

        let database_pools = Arc::new(DatabasePools {
            non_persons_reader: invalid_pool.clone(),
            non_persons_writer: invalid_pool.clone(),
            persons_reader: invalid_pool.clone(),
            persons_writer: invalid_pool,
            test_before_acquire: false,
        });

        // Startup should always return "started" even if warmup fails
        let result = startup(database_pools).await;
        assert_eq!(result, "started");
    }

    #[tokio::test]
    async fn test_startup_with_aliased_pools() {
        // Simulate the common case where persons pools are aliased to non-persons pools
        // (when persons_db_routing is disabled)
        let shared_pool = Arc::new(
            sqlx::postgres::PgPoolOptions::new()
                .max_connections(1)
                .acquire_timeout(std::time::Duration::from_millis(100))
                .connect_lazy("postgres://invalid:invalid@localhost:54321/nonexistent")
                .expect("Failed to create pool"),
        );

        // Both persons pools point to the same Arc as non-persons pools
        let database_pools = Arc::new(DatabasePools {
            non_persons_reader: shared_pool.clone(),
            non_persons_writer: shared_pool.clone(),
            persons_reader: shared_pool.clone(), // Aliased to non_persons_reader
            persons_writer: shared_pool,         // Aliased to non_persons_writer
            test_before_acquire: false,
        });

        // Startup should still return "started" and handle aliased pools gracefully
        let result = startup(database_pools).await;
        assert_eq!(result, "started");
    }
}
