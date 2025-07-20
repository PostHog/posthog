use axum::{
    routing::{post, get},
    Router,
};
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use sentry_forwarder::config::Config;
use sentry_forwarder::handler::{handle_sentry_event, handle_sentry_envelope};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::fmt::layer()
                .with_target(false)
                .with_thread_ids(true)
                .with_level(true)
        )
        .with(EnvFilter::from_default_env())
        .init();

    let config = Config::init_with_defaults().unwrap();
    let bind_address = format!("{}:{}", config.host, config.port);
    info!("Starting sentry-forwarder on {}", bind_address);

    let app = Router::new()
        .route("/", get(|| async { "Sentry to PostHog forwarder" }))
        .route("/api/:api_key/store", post(handle_sentry_event))
        .route("/api/:api_key/envelope", post(handle_sentry_envelope))
        .with_state(config);

    let listener = tokio::net::TcpListener::bind(&bind_address).await?;

    info!("Server listening on {}", bind_address);
    axum::serve(listener, app).await?;

    Ok(())
}
