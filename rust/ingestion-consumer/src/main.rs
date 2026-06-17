use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use envconfig::Envconfig;
use futures::future::ready;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder};
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use tracing::info;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use ingestion_consumer::config::Config;
use ingestion_consumer::consumer::IngestionConsumer;
use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::transport::HttpTransport;
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig};

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

    // Install Prometheus recorder with custom histogram buckets matching the
    // Node.js ingestion consumer, so existing dashboards and alerts work during switchover.
    let recorder_handle = if config.export_prometheus {
        Some(
            PrometheusBuilder::new()
                .set_buckets_for_metric(
                    Matcher::Full("ingestion_lag_ms_histogram".into()),
                    &[
                        1_000.0, 2_000.0, 5_000.0, 10_000.0, 30_000.0, 60_000.0, 120_000.0,
                        300_000.0, 600_000.0, 900_000.0,
                    ],
                )
                .expect("ingestion_lag_ms_histogram buckets")
                .set_buckets_for_metric(
                    Matcher::Full("consumer_batch_size".into()),
                    &[
                        0.0, 50.0, 100.0, 250.0, 500.0, 750.0, 1_000.0, 1_500.0, 2_000.0, 3_000.0,
                    ],
                )
                .expect("consumer_batch_size buckets")
                .set_buckets_for_metric(
                    Matcher::Full("consumer_batch_size_kb".into()),
                    &[
                        0.0, 128.0, 512.0, 1_024.0, 5_120.0, 10_240.0, 20_480.0, 51_200.0,
                        102_400.0, 204_800.0,
                    ],
                )
                .expect("consumer_batch_size_kb buckets")
                .install_recorder()
                .expect("failed to install Prometheus recorder"),
        )
    } else {
        None
    };

    let guard = manager.monitor_background();

    let worker_urls = config.worker_urls();

    // Build the worker health registry and start background probe tasks.
    let registry_config = WorkerRegistryConfig {
        probe_interval: Duration::from_millis(config.worker_probe_interval_ms),
        dead_declaration: Duration::from_millis(config.worker_dead_declaration_ms),
        passive_window: Duration::from_millis(config.worker_passive_window_ms),
        passive_error_threshold: config.worker_passive_error_threshold,
        passive_min_samples: config.worker_passive_min_samples,
        degraded_hold: Duration::from_millis(config.worker_degraded_hold_ms),
        min_state_duration: Duration::from_millis(config.worker_min_state_duration_ms),
        probe_failure_threshold: config.worker_probe_failure_threshold,
    };
    let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config));

    // Probe tasks run until the consumer shuts down.
    let probe_token = CancellationToken::new();
    Arc::clone(&registry).start_probing(probe_token.clone());

    let dispatcher = Arc::new(Dispatcher::with_strategy(
        Arc::clone(&registry),
        config.routing_strategy,
    ));

    let api_secret = if config.internal_api_secret.is_empty() {
        None
    } else {
        Some(config.internal_api_secret.clone())
    };
    let transport = Arc::new(HttpTransport::new(
        Duration::from_millis(config.http_timeout_ms),
        config.max_retries,
        api_secret,
        &worker_urls,
        config.ingestion_worker_concurrent_batches,
    ));

    let consumer = IngestionConsumer::new(&config, dispatcher, transport, consumer_handle)
        .context("Failed to create Kafka consumer")?;

    tokio::spawn(async move {
        consumer.process().await;
        // Cancel probe tasks once the consumer loop exits.
        probe_token.cancel();
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
