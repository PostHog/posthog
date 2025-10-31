use std::{future::ready, sync::Arc};

use crate::api::errors::AuthenticationErrorResponse;
use crate::billing_limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
use crate::database_pools::DatabasePools;
use axum::{
    http::{Method, StatusCode},
    response::{IntoResponse, Response},
    routing::{any, get},
    Json, Router,
};
use common_cookieless::CookielessManager;
use common_geoip::GeoIpClient;
use common_metrics::{setup_metrics_recorder, track_metrics};
use common_redis::Client as RedisClient;
use health::HealthRegistry;
use metrics::counter;
use tower::limit::ConcurrencyLimitLayer;
use tower_governor::{governor::GovernorConfigBuilder, GovernorLayer};
use tower_http::{
    cors::{AllowHeaders, AllowOrigin, CorsLayer},
    trace::TraceLayer,
};

use crate::{
    api::{
        endpoint, flag_definitions, flag_definitions_rate_limiter::FlagDefinitionsRateLimiter,
        flags_rate_limiter::FlagsRateLimiter, sse_endpoint,
    },
    cohorts::cohort_cache_manager::CohortCacheManager,
    config::{Config, TeamIdCollection},
    metrics::{
        consts::{FLAG_DEFINITIONS_RATE_LIMITED_COUNTER, FLAG_DEFINITIONS_REQUESTS_COUNTER},
        utils::team_id_label_filter,
    },
    sse::SseRedisSubscriptionManager,
};

#[derive(Clone)]
pub struct State {
    pub redis_reader: Arc<dyn RedisClient + Send + Sync>,
    pub redis_writer: Arc<dyn RedisClient + Send + Sync>,
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
    pub sse_manager: Option<Arc<SseRedisSubscriptionManager>>,
}

#[allow(clippy::too_many_arguments)]
pub fn router<RR, RW>(
    redis_reader: Arc<RR>,
    redis_writer: Arc<RW>,
    database_pools: Arc<DatabasePools>,
    cohort_cache: Arc<CohortCacheManager>,
    geoip: Arc<GeoIpClient>,
    liveness: HealthRegistry,
    feature_flags_billing_limiter: FeatureFlagsLimiter,
    session_replay_billing_limiter: SessionReplayLimiter,
    cookieless_manager: Arc<CookielessManager>,
    config: Config,
) -> Router
where
    RR: RedisClient + Send + Sync + 'static,
    RW: RedisClient + Send + Sync + 'static,
{
    // Initialize flag definitions rate limiter with default and custom team rates
    let flag_definitions_limiter = FlagDefinitionsRateLimiter::new(
        config.flag_definitions_default_rate_per_minute,
        config.flag_definitions_rate_limits.0.clone(),
        FLAG_DEFINITIONS_REQUESTS_COUNTER,
        FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
    )
    .expect("Failed to initialize flag definitions rate limiter");

    // Initialize rate limiter with configuration
    let flags_rate_limiter = FlagsRateLimiter::new(
        *config.flags_rate_limit_enabled,
        config.flags_bucket_replenish_rate,
        config.flags_bucket_capacity,
    )
    .unwrap_or_else(|e| {
        panic!(
            "Invalid rate limit configuration: {e}. \
             Check FLAGS_BUCKET_REPLENISH_RATE (must be > 0) and FLAGS_BUCKET_CAPACITY (must be > 0)"
        )
    });

    // Initialize SSE manager for real-time feature flag updates
    // For now, use a simple Redis URL - in production, this should come from config
    let redis_url =
        std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string());
    let sse_manager = Arc::new(SseRedisSubscriptionManager::new(redis_url));

    let state = State {
        redis_reader,
        redis_writer,
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
        sse_manager: Some(sse_manager),
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
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())));

    // flags endpoint
    // Build flags router with optional IP rate limiting
    let mut flags_router = Router::new()
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
        .route("/flags/stream", get(sse_endpoint::feature_flags_stream))
        .route("/flags/stream/", get(sse_endpoint::feature_flags_stream))
        .route("/decide", any(endpoint::flags))
        .route("/decide/", any(endpoint::flags))
        .layer(ConcurrencyLimitLayer::new(config.max_concurrency));

    // Apply IP-based rate limiting if enabled
    // This provides defense-in-depth against DDoS with rotating fake tokens
    if *config.flags_ip_rate_limit_enabled {
        let governor_conf = if config.flags_ip_replenish_rate >= 1.0 {
            // For rates >= 1, use per_second
            Arc::new(
                GovernorConfigBuilder::default()
                    .per_second(config.flags_ip_replenish_rate as u64)
                    .burst_size(config.flags_ip_burst_size)
                    .error_handler(rate_limit_error_response)
                    .finish()
                    .expect("Invalid IP rate limit configuration"),
            )
        } else {
            // For fractional rates < 1, use per_millisecond
            // e.g., 0.1/sec = 1 per 10 seconds = 1 per 10000ms
            let period_ms = (1000.0 / config.flags_ip_replenish_rate) as u64;
            Arc::new(
                GovernorConfigBuilder::default()
                    .per_millisecond(period_ms)
                    .burst_size(config.flags_ip_burst_size)
                    .error_handler(rate_limit_error_response)
                    .finish()
                    .expect("Invalid IP rate limit configuration"),
            )
        };

        flags_router = flags_router.layer(GovernorLayer {
            config: governor_conf,
        });
    }

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

pub async fn index() -> &'static str {
    "feature flags"
}

/// Custom error handler for IP-based rate limiting.
/// Returns the same JSON format as token-based rate limiting for consistency.
fn rate_limit_error_response(_err: tower_governor::GovernorError) -> Response {
    // Track IP-based rate limit violations
    // Note: We don't include the IP address in labels to avoid high cardinality
    // in metrics (an attacker could create millions of unique IPs)
    counter!("flags_ip_rate_limit_exceeded_total").increment(1);

    let error_response = AuthenticationErrorResponse {
        error_type: "validation_error".to_string(),
        code: "rate_limit_exceeded".to_string(),
        detail: "Rate limit exceeded".to_string(),
        attr: None,
    };

    (StatusCode::TOO_MANY_REQUESTS, Json(error_response)).into_response()
}
