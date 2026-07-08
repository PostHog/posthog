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
use tracing::{error, info};
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use ingestion_consumer::config::Config;
use ingestion_consumer::consumer::IngestionConsumer;
use ingestion_consumer::discovery::{
    DiscoveryMode, EndpointSliceDiscovery, StaticDiscovery, WorkerDiscovery,
};
use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::transport::HttpTransport;
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig};

common_alloc::used!();

fn main() -> Result<()> {
    // Install a process-wide rustls CryptoProvider before any TLS use. kube's
    // HTTPS client (EndpointSlice discovery) uses rustls 0.23, which can't
    // auto-pick a provider with both aws-lc-rs and ring compiled in — it panics.
    // Matches personhog-router / cymbal / kafka-assigner.
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install rustls ring CryptoProvider");

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

    info!("Starting ingestion consumer");

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
        let mut builder = PrometheusBuilder::new()
            .set_buckets_for_metric(
                Matcher::Full("ingestion_lag_ms_histogram".into()),
                &[
                    1_000.0, 2_000.0, 5_000.0, 10_000.0, 30_000.0, 60_000.0, 120_000.0, 300_000.0,
                    600_000.0, 900_000.0,
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
                    0.0, 128.0, 512.0, 1_024.0, 5_120.0, 10_240.0, 20_480.0, 51_200.0, 102_400.0,
                    204_800.0,
                ],
            )
            .expect("consumer_batch_size_kb buckets");

        // Global default labels (match the Node.js `initializePrometheusLabels`
        // defaults): every metric carries ingestion_pipeline / ingestion_lane so
        // dashboards, alerts, and the lag-based KEDA autoscaler select this
        // consumer's series — notably `ingestion_lag_ms` for the scaling triggers.
        if let Some(pipeline) = config.ingestion_pipeline.as_deref() {
            builder = builder.add_global_label("ingestion_pipeline", pipeline);
        }
        if let Some(lane) = config.ingestion_lane.as_deref() {
            builder = builder.add_global_label("ingestion_lane", lane);
        }

        Some(
            builder
                .install_recorder()
                .expect("failed to install Prometheus recorder"),
        )
    } else {
        None
    };

    let guard = manager.monitor_background();

    // Build the worker health registry empty; the discovery provider below
    // populates it (statically from config, or dynamically from EndpointSlices).
    let registry_config = WorkerRegistryConfig::from(&config);
    let registry = Arc::new(WorkerRegistry::new(&[], registry_config));

    // Probe tasks run until shutdown.
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
    // Transport semaphores are created lazily per worker, so it starts empty.
    let transport = Arc::new(HttpTransport::new(
        Duration::from_millis(config.http_timeout_ms),
        config.max_retries,
        api_secret,
        &[],
        config.ingestion_worker_concurrent_batches,
    ));

    // Select the worker discovery provider and start it (static applies the
    // configured list immediately; endpointslice watches and keeps in sync).
    let discovery_token = CancellationToken::new();
    let discovery: Box<dyn WorkerDiscovery> = match config.worker_discovery_mode {
        DiscoveryMode::Static => Box::new(StaticDiscovery::new(config.worker_urls())),
        DiscoveryMode::EndpointSlice => {
            if config.worker_service_name.is_empty() {
                anyhow::bail!("WORKER_SERVICE_NAME is required for endpointslice discovery");
            }
            let client = kube::Client::try_default()
                .await
                .context("Failed to create Kubernetes client for EndpointSlice discovery")?;
            Box::new(EndpointSliceDiscovery::new(
                client,
                config.worker_namespace.clone(),
                config.worker_service_name.clone(),
                config.worker_port,
            ))
        }
    };
    let _discovery_handle = discovery.start(Arc::clone(&registry), discovery_token.clone());

    // Reap drained workers: once a departed worker has finished its in-flight
    // batches (or hit the drain timeout), remove it from the registry and prune
    // its transport semaphore. No-op in static mode (workers never drain).
    {
        let registry = Arc::clone(&registry);
        let transport = Arc::clone(&transport);
        let dispatcher = Arc::clone(&dispatcher);
        let token = probe_token.clone();
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = token.cancelled() => break,
                    _ = tokio::time::sleep(Duration::from_secs(1)) => {}
                }
                // A worker that left the pool while idle has no in-flight to
                // resolve, so `on_sub_batch_resolved` never completes its drain.
                // Complete it here so it's reaped now rather than at the timeout.
                for worker in registry.draining_workers() {
                    if !dispatcher.has_in_flight(&worker) {
                        registry.complete_drain(&worker);
                    }
                }
                for worker in registry.reapable_workers() {
                    registry.remove_worker(&worker);
                    transport.remove_worker(&worker);
                }
            }
        });
    }

    // Build and serve the health/metrics HTTP server BEFORE gating on worker
    // discovery. Otherwise /_readiness and /_liveness stay unbound while we wait
    // for the first workers, so kubelet sees "connection refused" instead of a
    // proper 503 — and since /_liveness is meant to always answer 200, an unbound
    // port lets the liveness probe kill the pod mid-startup.
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
    tokio::spawn(async move {
        if let Err(err) = axum::serve(listener, app)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
        {
            error!(error = %err, "Health/metrics server error");
        }
        metrics_handle.work_completed();
    });

    // For dynamic discovery, wait for the first workers before consuming so the
    // first batch has somewhere to route. Readiness stays 503 until the consumer
    // starts; the server above keeps the probes answering during the wait.
    if config.worker_discovery_mode == DiscoveryMode::EndpointSlice {
        info!("Waiting for the first workers from EndpointSlice discovery");
        while registry.worker_count() == 0 {
            tokio::select! {
                _ = consumer_handle.shutdown_recv() => {
                    info!("Shutdown received while waiting for worker discovery");
                    break;
                }
                _ = tokio::time::sleep(Duration::from_millis(250)) => {}
            }
        }
    }

    let consumer = IngestionConsumer::new(&config, dispatcher, transport, consumer_handle)
        .context("Failed to create Kafka consumer")?;

    tokio::spawn(async move {
        consumer.process().await;
        // Cancel background tasks once the consumer loop exits.
        probe_token.cancel();
        discovery_token.cancel();
    });

    guard.wait().await?;

    info!("Ingestion consumer stopped");
    Ok(())
}
