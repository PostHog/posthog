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
use common_metrics::{setup_metrics_recorder, track_metrics};
use common_redis::Client as RedisClient;
use health::HealthRegistry;
use metrics::gauge;
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
    };

    // Very permissive CORS policy, as old SDK versions
    // and reverse proxies might send funky headers.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS, Method::HEAD])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    // liveness/readiness checks
    let status_router = Router::new()
        .route("/", get(index))
        .route(
            "/_readiness",
            get(move || readiness(db_pools_for_readiness.clone())),
        )
        .route("/_liveness", get(move || ready(liveness.get_status())));

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

pub async fn readiness(
    database_pools: Arc<DatabasePools>,
) -> Result<&'static str, (StatusCode, String)> {
    // Check all pools and collect errors
    let pools = [
        ("non_persons_reader", &database_pools.non_persons_reader),
        ("non_persons_writer", &database_pools.non_persons_writer),
        ("persons_reader", &database_pools.persons_reader),
        ("persons_writer", &database_pools.persons_writer),
    ];

    for (name, pool) in pools {
        let mut conn = pool.acquire().await.map_err(|e| {
            (
                StatusCode::SERVICE_UNAVAILABLE,
                format!("{name} pool unavailable: {e}"),
            )
        })?;

        // If test_before_acquire is false, explicitly test the connection
        if !database_pools.test_before_acquire {
            sqlx::query("SELECT 1")
                .execute(&mut *conn)
                .await
                .map_err(|e| {
                    (
                        StatusCode::SERVICE_UNAVAILABLE,
                        format!("{name} connection test failed: {e}"),
                    )
                })?;
        }
    }

    Ok("ready")
}

pub async fn index() -> &'static str {
    "feature flags"
}
