use std::sync::Arc;
use std::time::Duration;

use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use lifecycle::{ComponentOptions, Manager};
use serve_metrics::setup_metrics_routes;
use sqlx::postgres::PgPoolOptions;
use tokio::net::TcpListener;
use tracing::info;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use common_redis::{CompressionConfig, RedisClient, RedisValueFormat};

use integration_gateway::app_context::AppState;
use integration_gateway::cache;
use integration_gateway::config::Config;
use integration_gateway::crypto::IntegrationDecryptor;
use integration_gateway::integrations::IntegrationService;
use integration_gateway::refresh::RefreshManager;
use integration_gateway::router as gw_router;

common_alloc::used!();

fn setup_tracing() {
    // JSON logs so the per-caller audit events (target integration_gateway::audit) are queryable.
    let log_layer = tracing_subscriber::fmt::layer().json().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy(),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

async fn index() -> &'static str {
    "integration-gateway"
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();
    info!("Starting integration-gateway...");

    let config = Config::init()?;

    // Build the decryptor first, so a missing/invalid ENCRYPTION_SALT_KEYS fails startup loudly
    // rather than surfacing as opaque per-request decrypt failures later.
    let decryptor = IntegrationDecryptor::build(
        &config.encryption_salt_keys_list(),
        &config.legacy_secret_keys(),
        &config.salt_keys(),
    )?;
    info!(
        primary_keys = decryptor.primary_key_count(),
        legacy_keys = decryptor.legacy_key_count(),
        "Built integration decryptor"
    );

    let jwt_secrets = config.jwt_secrets();
    if jwt_secrets.is_empty() {
        tracing::warn!(
            "INTEGRATION_GATEWAY_JWT_SECRET is empty; every request will be rejected (fail closed)"
        );
    }

    let pool = PgPoolOptions::new()
        .max_connections(config.max_pg_connections)
        .connect(&config.database_url)
        .await?;

    let cache = cache::build(config.cache_ttl_seconds, config.cache_max_capacity);

    // Token refresh (writer) is opt-in per kind. With no kinds configured we skip Redis entirely and
    // run pure pass-through (Django's beat owns all refresh), keeping the read-only deploy free of a
    // Redis dependency.
    let refresh_manager = if config.refresh_kinds_list().is_empty() {
        info!("No refresh_kinds configured; token refresh disabled (pass-through)");
        None
    } else {
        let redis = RedisClient::with_config(
            config.redis_url.clone(),
            CompressionConfig::disabled(),
            RedisValueFormat::Utf8,
            Some(Duration::from_millis(500)),
            Some(Duration::from_secs(5)),
        )
        .await?;
        info!(kinds = ?config.refresh_kinds_list(), "Token refresh enabled");
        Some(Arc::new(RefreshManager::new(
            pool.clone(),
            Arc::new(redis),
            decryptor.clone(),
            Arc::new(config.clone()),
        )))
    };

    let service = Arc::new(IntegrationService::new(
        pool,
        decryptor,
        cache,
        refresh_manager,
    ));

    let state = AppState {
        service,
        jwt_secrets: Arc::new(jwt_secrets),
        max_batch_size: config.max_batch_size,
    };

    // Lifecycle: signals, health, coordinated shutdown. Single observability component (the HTTP
    // server) — no background workers in v1.
    let mut manager = Manager::builder("integration-gateway")
        .with_global_shutdown_timeout(Duration::from_secs(60))
        .build();
    let metrics_handle = manager.register("server", ComponentOptions::new().is_observability(true));
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let guard = manager.monitor_background();

    let app = Router::new()
        .route("/", get(index))
        .route(
            "/_readiness",
            get({
                let r = readiness.clone();
                move || {
                    let r = r.clone();
                    async move { r.check().await }
                }
            }),
        )
        .route(
            "/_liveness",
            get({
                let l = liveness.clone();
                move || {
                    let l = l.clone();
                    async move { l.check().into_response() }
                }
            }),
        );
    let app = gw_router::merge_api_routes(app, state);
    let app = setup_metrics_routes(app);

    let bind = format!("{}:{}", config.host, config.port);
    info!(address = %bind, "integration-gateway HTTP server starting");
    let listener = TcpListener::bind(&bind).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await?;
    metrics_handle.work_completed();

    guard.wait().await?;
    info!("integration-gateway stopped");
    Ok(())
}
