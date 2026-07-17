use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use axum::response::IntoResponse;
use axum::routing::get;
use axum::Router;
use envconfig::Envconfig;
use futures::future::ready;
use futures::StreamExt;
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
use ingestion_consumer::debug_recorder::{DebugLoad, DebugRecorder, DebugState, WorkerStatus};
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

    // Debug event recorder: a bounded in-memory event buffer plus live
    // broadcast, injected into every component below and served by the /debug
    // API (consumed by the ingestion control plane UI). `None` (the default)
    // records nothing. Fail closed: enabling without the dedicated secret
    // mounts nothing rather than exposing the API unauthenticated.
    let debug_recorder = if config.debug_api_enabled && !config.debug_api_secret.is_empty() {
        Some(DebugRecorder::new(5_000, Duration::from_secs(900)))
    } else {
        if config.debug_api_enabled {
            error!("DEBUG_API_ENABLED is set but DEBUG_API_SECRET is empty; debug API disabled");
        }
        None
    };

    // Build the worker health registry empty; the discovery provider below
    // populates it (statically from config, or dynamically from EndpointSlices).
    let registry_config = WorkerRegistryConfig::from(&config);
    let mut registry = WorkerRegistry::new(&[], registry_config);
    if let Some(recorder) = &debug_recorder {
        registry.set_debug_recorder(Arc::clone(recorder));
    }
    let registry = Arc::new(registry);

    // Probe tasks run until shutdown.
    let probe_token = CancellationToken::new();
    Arc::clone(&registry).start_probing(probe_token.clone());

    let mut dispatcher = Dispatcher::with_strategy(Arc::clone(&registry), config.routing_strategy);
    if let Some(recorder) = &debug_recorder {
        dispatcher.set_debug_recorder(Arc::clone(recorder));
    }
    let dispatcher = Arc::new(dispatcher);

    let api_secret = if config.internal_api_secret.is_empty() {
        None
    } else {
        Some(config.internal_api_secret.clone())
    };
    // Transport semaphores are created lazily per worker, so it starts empty.
    let mut transport = HttpTransport::new(
        Duration::from_millis(config.http_timeout_ms),
        config.max_retries,
        api_secret,
        &[],
        config.ingestion_worker_concurrent_batches,
    );
    if let Some(recorder) = &debug_recorder {
        transport.set_debug_recorder(Arc::clone(recorder));
    }
    let transport = Arc::new(transport);

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

    // Debug API: fast load snapshots, a full state snapshot, and the live SSE
    // event feed, consumed by the ingestion control plane UI. Only mounted
    // when DEBUG_API_ENABLED, and every request must present the dedicated
    // DEBUG_API_SECRET (the health server binds broadly by default, so the
    // routes must not be open to anything that can reach the port).
    if let Some(recorder) = &debug_recorder {
        let secret: Arc<str> = Arc::from(config.debug_api_secret.as_str());
        let group_id = config.ingestion_consumer_group_id.clone();
        {
            let registry = Arc::clone(&registry);
            let dispatcher = Arc::clone(&dispatcher);
            let group_id = group_id.clone();
            let secret = Arc::clone(&secret);
            app = app.route(
                "/debug/load",
                get(move |headers: axum::http::HeaderMap| {
                    let result = if !debug_authorized(&headers, &secret) {
                        Err(axum::http::StatusCode::UNAUTHORIZED)
                    } else {
                        Ok(axum::Json(build_debug_load(
                            &group_id,
                            &registry,
                            &dispatcher,
                        )))
                    };
                    ready(result)
                }),
            );
        }
        {
            let recorder = Arc::clone(recorder);
            let registry = Arc::clone(&registry);
            let dispatcher = Arc::clone(&dispatcher);
            let group_id = group_id.clone();
            let secret = Arc::clone(&secret);
            app = app.route(
                "/debug/state",
                get(move |headers: axum::http::HeaderMap| {
                    let result = if !debug_authorized(&headers, &secret) {
                        Err(axum::http::StatusCode::UNAUTHORIZED)
                    } else {
                        let load = build_debug_load(&group_id, &registry, &dispatcher);
                        Ok(axum::Json(DebugState {
                            group_id: load.group_id,
                            workers: load.workers,
                            dispatcher: load.dispatcher,
                            events: recorder.backlog(),
                        }))
                    };
                    ready(result)
                }),
            );
        }
        {
            let recorder = Arc::clone(recorder);
            let secret = Arc::clone(&secret);
            // Cap concurrent SSE subscribers: each replays the retained backlog
            // and then holds a connection open, so an unbounded count could
            // pressure the shared health server.
            let active_subscribers = Arc::new(std::sync::atomic::AtomicUsize::new(0));
            app = app.route(
                "/debug/events",
                get(move |headers: axum::http::HeaderMap| {
                    let response = if !debug_authorized(&headers, &secret) {
                        Err(axum::http::StatusCode::UNAUTHORIZED)
                    } else if active_subscribers.fetch_add(1, std::sync::atomic::Ordering::SeqCst)
                        >= MAX_SSE_SUBSCRIBERS
                    {
                        active_subscribers.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
                        Err(axum::http::StatusCode::TOO_MANY_REQUESTS)
                    } else {
                        // Decrements when the stream (and the closure owning the
                        // guard) is dropped, covering client disconnects.
                        let guard = SseSlotGuard(Arc::clone(&active_subscribers));
                        // Subscribe BEFORE snapshotting the backlog so an event
                        // recorded in between lands in the channel instead of
                        // being missed; the seq filter below drops the overlap
                        // (events present in both the backlog and the channel).
                        let rx = recorder.subscribe();
                        let backlog = recorder.backlog();
                        let last_backlog_seq = backlog.last().map(|e| e.seq);
                        let live = futures::stream::unfold(rx, |mut rx| async {
                            loop {
                                // A lagged subscriber skips dropped events
                                // rather than dying.
                                match rx.recv().await {
                                    Ok(event) => return Some((event, rx)),
                                    Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {
                                        continue
                                    }
                                    Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                                        return None
                                    }
                                }
                            }
                        })
                        .filter(move |event| {
                            ready(last_backlog_seq.is_none_or(|seq| event.seq > seq))
                        });
                        let stream = futures::stream::iter(backlog)
                            .chain(live)
                            .map(move |event| {
                                let _held = &guard;
                                axum::response::sse::Event::default().json_data(&event)
                            });
                        Ok(axum::response::Sse::new(stream)
                            .keep_alive(axum::response::sse::KeepAlive::default()))
                    };
                    ready(response)
                }),
            );
        }
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

    let consumer = IngestionConsumer::new(
        &config,
        Arc::clone(&dispatcher),
        transport,
        consumer_handle,
        debug_recorder,
    )
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

/// Maximum concurrent `/debug/events` SSE subscribers.
const MAX_SSE_SUBSCRIBERS: usize = 8;

/// Releases an SSE subscriber slot when the stream is dropped.
struct SseSlotGuard(Arc<std::sync::atomic::AtomicUsize>);

impl Drop for SseSlotGuard {
    fn drop(&mut self) {
        self.0.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
    }
}

/// Whether the request carries the dedicated debug API secret. The secret is
/// never empty here (an empty secret disables the API entirely).
fn debug_authorized(headers: &axum::http::HeaderMap, secret: &str) -> bool {
    headers
        .get("x-debug-api-secret")
        .and_then(|value| value.to_str().ok())
        .is_some_and(|presented| constant_time_eq(presented, secret))
}

/// Compare without short-circuiting on the first mismatched byte, so response
/// timing doesn't leak how much of the secret matched.
fn constant_time_eq(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// Merge the registry's health snapshots with the dispatcher's in-flight load
/// into the `/debug/load` payload.
fn build_debug_load(
    group_id: &str,
    registry: &ingestion_consumer::worker_registry::WorkerRegistry,
    dispatcher: &Dispatcher,
) -> DebugLoad {
    let dispatcher_load = dispatcher.debug_load();
    let workers = registry
        .health_snapshots()
        .into_iter()
        .map(|snap| {
            let in_flight_messages = dispatcher_load
                .per_worker
                .iter()
                .find(|entry| entry.worker == snap.url)
                .map(|entry| entry.in_flight)
                .unwrap_or(0);
            WorkerStatus {
                url: snap.url,
                state: snap.state,
                draining: snap.draining,
                consecutive_probe_failures: snap.consecutive_probe_failures,
                passive_error_rate: snap.passive_error_rate,
                passive_samples: snap.passive_samples,
                in_flight_messages,
            }
        })
        .collect();
    DebugLoad {
        group_id: group_id.to_string(),
        workers,
        dispatcher: dispatcher_load,
    }
}
