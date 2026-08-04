use std::future::ready;
use std::sync::Arc;
use std::time::Duration;

use axum::routing::get;
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use health::{readiness_handler, HealthRegistry};
use kafka_manager::api;
use kafka_manager::config::Config;
use kafka_manager::state::FleetState;
use tokio::signal;
use tracing::info;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

async fn shutdown() {
    let mut term = signal::unix::signal(signal::unix::SignalKind::terminate())
        .expect("failed to register SIGTERM handler");
    let mut interrupt = signal::unix::signal(signal::unix::SignalKind::interrupt())
        .expect("failed to register SIGINT handler");

    tokio::select! {
        _ = term.recv() => {},
        _ = interrupt.recv() => {},
    };

    info!("Shutting down gracefully...");
}

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().json().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy(),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

#[tokio::main]
async fn main() {
    setup_tracing();
    info!("Starting kafka-manager...");

    let config = Config::init_from_env().expect("failed to load config");
    let bind = format!("{}:{}", config.host, config.port);

    // No long-running pipeline to healthcheck; the sweep loop doubles as the
    // liveness heartbeat so a wedged state lock fails the probe.
    let health_registry = HealthRegistry::new("liveness");
    let sweeper_health = health_registry
        .register("sweeper".to_string(), Duration::from_secs(30))
        .await;

    let state = Arc::new(FleetState::new(Duration::from_secs(config.pod_ttl_seconds)));

    let sweep_state = state.clone();
    let sweep_interval = Duration::from_secs(config.sweep_interval_seconds.max(1));
    tokio::spawn(async move {
        loop {
            sweep_state.sweep();
            sweeper_health.report_healthy().await;
            tokio::time::sleep(sweep_interval).await;
        }
    });

    let router = api::router(state)
        .route("/_readiness", get(readiness_handler))
        .route(
            "/_liveness",
            get(move || ready(health_registry.get_status())),
        );
    let router = setup_metrics_routes(router);

    info!("Listening on {}", bind);
    let listener = tokio::net::TcpListener::bind(bind)
        .await
        .expect("could not bind port");

    axum::serve(listener, router)
        .with_graceful_shutdown(shutdown())
        .await
        .expect("server failed");
}
