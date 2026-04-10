use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use envconfig::Envconfig;
use futures::future::ready;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::PrometheusBuilder;
use tokio::net::TcpListener;
use tracing::info;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use ingestion_consumer::config::Config;
use ingestion_consumer::consumer::IngestionConsumer;
use ingestion_consumer::transport::HttpTransport;

common_alloc::used!();

fn main() -> Result<()> {
    let config = Config::init_from_env()
        .context("Failed to load configuration from environment variables")?;

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("Failed to build tokio runtime")?;

    runtime.block_on(async_main(config))
}

async fn async_main(config: Config) -> Result<()> {
    let is_debug = std::env::var("RUST_LOG")
        .map(|v| v.contains("debug"))
        .unwrap_or(false);

    let log_layer = if is_debug {
        fmt::layer()
            .with_target(true)
            .with_level(true)
            .with_ansi(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
                    .from_env_lossy(),
            )
            .boxed()
    } else {
        fmt::layer()
            .json()
            .flatten_event(true)
            .with_current_span(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
                    .from_env_lossy(),
            )
            .boxed()
    };

    tracing_subscriber::registry().with(log_layer).init();

    info!(?config, "Starting ingestion consumer");

    // Lifecycle manager handles signals, health, and shutdown coordination
    let mut manager = Manager::builder("ingestion-consumer")
        .with_global_shutdown_timeout(Duration::from_secs(90))
        .build();

    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(60))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    // Install Prometheus recorder
    let recorder_handle = if config.export_prometheus {
        Some(
            PrometheusBuilder::new()
                .install_recorder()
                .expect("failed to install Prometheus recorder"),
        )
    } else {
        None
    };

    let guard = manager.monitor_background();

    // Spawn the consumer task
    let api_secret = if config.internal_api_secret.is_empty() {
        None
    } else {
        Some(config.internal_api_secret.clone())
    };
    let transport = Arc::new(HttpTransport::new(
        Duration::from_millis(config.http_timeout_ms),
        config.max_retries,
        api_secret,
    ));

    let consumer = IngestionConsumer::new(&config, transport, consumer_handle)
        .context("Failed to create Kafka consumer")?;

    tokio::spawn(async move {
        consumer.process().await;
    });

    // Build and serve the health/metrics HTTP server
    let mut app = Router::new()
        .route("/", get(|| async { "ingestion consumer" }))
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

    if let Some(handle) = recorder_handle {
        app = app.route("/metrics", get(move || ready(handle.render())));
    }

    let bind = config.bind_address();
    info!(address = %bind, "Health/metrics server starting");

    let listener = TcpListener::bind(&bind).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await?;
    metrics_handle.work_completed();

    guard.wait().await?;

    info!("Ingestion consumer stopped");
    Ok(())
}
