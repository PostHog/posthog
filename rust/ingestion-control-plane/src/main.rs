use std::future::ready;
use std::time::Duration;

use axum::routing::get;
use common_metrics::setup_metrics_routes;
use health::{readiness_handler, HealthRegistry};
use ingestion_control_plane::api;
use ingestion_control_plane::config::Config;
use ingestion_control_plane::state::AppState;
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
    info!("Starting ingestion-control-plane...");

    // kube's rustls-based client needs a process-wide crypto provider.
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install rustls crypto provider");

    let config = Config::init_with_defaults().expect("failed to load config");
    let bind = format!("{}:{}", config.host, config.port);

    // This service has no long-running pipeline to healthcheck; a heartbeat
    // task proves the runtime is alive so the liveness probe passes.
    let health_registry = HealthRegistry::new("liveness");
    let heartbeat = health_registry
        .register("heartbeat".to_string(), Duration::from_secs(30))
        .await;
    tokio::spawn(async move {
        loop {
            heartbeat.report_healthy().await;
            tokio::time::sleep(Duration::from_secs(10)).await;
        }
    });

    let state = AppState::new(config).expect("failed to initialize app state");

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
