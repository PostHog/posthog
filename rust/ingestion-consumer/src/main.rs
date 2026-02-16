use std::future::ready;
use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_metrics::{serve, setup_metrics_routes};
use envconfig::Envconfig;
use tracing::level_filters::LevelFilter;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

mod config;
mod consumer;
mod error;
mod router;
mod transport;
mod types;

use config::Config;
use consumer::IngestionConsumerLoop;
use transport::HttpJsonTransport;

common_alloc::used!();

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy()
            .add_directive("rdkafka=warn".parse().unwrap()),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "ingestion consumer"
}

#[tokio::main]
pub async fn main() -> Result<(), anyhow::Error> {
    setup_tracing();
    info!("Starting ingestion consumer...");

    let config = Config::init_from_env()?;

    let targets = config.target_addresses();
    info!(
        targets = ?targets,
        topic = config.kafka_topic,
        group_id = config.kafka_group_id,
        batch_size = config.batch_size,
        "Configuration loaded"
    );

    // Health check server
    let bind = format!("{}:{}", config.bind_host, config.bind_port);
    let health_router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(|| ready("ok")));
    let health_router = setup_metrics_routes(health_router);

    tokio::task::spawn(async move {
        serve(health_router, &bind)
            .await
            .expect("failed to start health server");
    });

    // Shutdown signal
    let (shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);

    tokio::spawn(async move {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to listen for ctrl+c");
        info!("Shutdown signal received");
        let _ = shutdown_tx.send(true);
    });

    // Transport
    let transport = Arc::new(HttpJsonTransport::new(
        Duration::from_millis(config.http_timeout_ms),
        config.max_retries,
    ));

    // Consumer loop
    let consumer_loop = IngestionConsumerLoop::new(&config, transport)?;
    consumer_loop.run(shutdown_rx).await?;

    info!("Ingestion consumer shut down");
    Ok(())
}
