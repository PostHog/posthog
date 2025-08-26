use anyhow::{Context, Result};
use axum::{routing::get, Router};
use futures::future::ready;
use health::HealthRegistry;
use serve_metrics::{serve, setup_metrics_recorder};
use tokio::task::JoinHandle;
use tracing::info;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use kafka_deduplicator::{config::Config, service::KafkaDeduplicatorService};

common_alloc::used!();

pub async fn index() -> &'static str {
    "kafka deduplicator service"
}

fn start_server(config: &Config, liveness: HealthRegistry) -> JoinHandle<()> {
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())));

    // Don't install metrics unless asked to
    // Installing a global recorder when capture is used as a library (during tests etc)
    // does not work well.
    let router = if config.export_prometheus {
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    };

    let bind = config.bind_address();

    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize tracing with EnvFilter for RUST_LOG support
    // Default to INFO level if RUST_LOG is not set
    let log_filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));

    tracing_subscriber::registry()
        .with(tracing_subscriber::fmt::layer())
        .with(log_filter)
        .init();

    info!("Starting Kafka Deduplicator service");

    // Load configuration using PostHog pattern
    let config = Config::init_with_defaults()
        .context("Failed to load configuration from environment variables. Please check your environment setup.")?;

    info!("Configuration loaded: {:?}", config);

    // Create health registry for liveness checks
    let liveness = HealthRegistry::new("liveness");

    // Start HTTP server with metrics endpoint
    let server_handle = start_server(&config, liveness.clone());
    info!("Started metrics server on {}", config.bind_address());

    // Create and run the service
    let service = KafkaDeduplicatorService::new(config, liveness)
        .with_context(|| "Failed to create Kafka Deduplicator service. Check your Kafka connection and RocksDB configuration.".to_string())?;

    // Run the service (this blocks until shutdown)
    service.run().await?;

    // Clean up metrics server
    server_handle.abort();

    Ok(())
}
