use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;

use axum::{http::StatusCode, routing::get, Router};
use cymbal::config::Config as CymbalConfig;
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolutionServer;
use cymbal_resolution::app_context::AppContext;
use cymbal_resolution::auth::InternalApiSecretInterceptor;
use cymbal_resolution::config::Config;
use cymbal_resolution::load_monitor::LoadMonitor;
use cymbal_resolution::service::{
    CymbalResolutionService, ServiceConfig, ITEM_DURATION_BUCKETS_MS,
};
use envconfig::Envconfig;
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

common_alloc::used!();

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    init_tracing();

    let config = Config::init_from_env().expect("Invalid cymbal-resolution configuration");
    let cymbal_config = CymbalConfig::init_with_defaults().expect("Invalid cymbal configuration");
    init_posthog_client(&cymbal_config).await;

    tracing::info!("Starting cymbal-resolution service");
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!("Metrics port: {}", config.metrics_port);

    let app_context = AppContext::from_config(config.clone(), &cymbal_config)
        .await
        .expect("Failed to build cymbal-resolution app context");

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let draining = Arc::new(AtomicBool::new(false));
    let drain_notice = Duration::from_millis(config.subscribe_tick_interval_ms).saturating_mul(2);
    let _shutdown_handle = spawn_shutdown_listener(
        shutdown_tx.clone(),
        draining.clone(),
        app_context.load_monitor.clone(),
        drain_notice,
    );
    let metrics_handle =
        spawn_metrics_server(config.metrics_port, shutdown_rx.clone(), draining.clone());

    let service_config = ServiceConfig::from(&config);
    let service = CymbalResolutionService::new(
        app_context.symbol_resolver.clone(),
        app_context.symbol_resolution_limiter.clone(),
        app_context.load_monitor.clone(),
        app_context.service_instance_id.clone(),
        service_config,
        draining,
    );
    let auth_interceptor = InternalApiSecretInterceptor::new(config.internal_api_secret.clone());

    let listener = tokio::net::TcpListener::bind(config.grpc_address).await?;
    let incoming = tracked_tcp_incoming(listener);

    tracing::info!("gRPC server listening on {}", config.grpc_address);

    let server_result = Server::builder()
        .http2_keepalive_interval(Some(Duration::from_secs(30)))
        .http2_keepalive_timeout(Some(Duration::from_secs(20)))
        .layer(GrpcMetricsLayer::default().with_processing_time_header())
        .layer(GrpcLoadShedLayer::new(config.max_concurrent_requests))
        // The cymbal client submits exception-level ResolveItems. The server
        // relies on tonic's 4 MiB per-message default; an oversized item
        // surfaces as `InvalidArgument`. Future: signal "send smaller" back
        // via `LoadEvent`.
        .add_service(CymbalResolutionServer::with_interceptor(
            service,
            move |request| auth_interceptor.authenticate(request),
        ))
        .serve_with_incoming_shutdown(incoming, wait_for_shutdown(shutdown_rx))
        .await;

    let _ignored = shutdown_tx.send(true);
    if let Err(err) = metrics_handle.await {
        tracing::warn!(error = %err, "metrics server task failed during shutdown");
    }
    server_result?;

    Ok(())
}

async fn init_posthog_client(config: &CymbalConfig) {
    match &config.posthog_api_key {
        Some(key) => {
            let ph_config = posthog_rs::ClientOptionsBuilder::default()
                .api_key(key.clone())
                .api_endpoint(config.posthog_endpoint.clone())
                .build()
                .expect("Invalid PostHog client configuration");
            posthog_rs::init_global(ph_config)
                .await
                .expect("Failed to initialize PostHog client");
            tracing::info!("PostHog client initialized");
        }
        None => {
            posthog_rs::disable_global();
            tracing::warn!("PostHog client disabled");
        }
    }
}

fn init_tracing() {
    let log_layer = fmt::layer()
        .with_target(true)
        .with_thread_ids(true)
        .with_level(true);

    tracing_subscriber::registry()
        .with(log_layer)
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();
}

fn spawn_metrics_server(
    port: u16,
    shutdown_rx: watch::Receiver<bool>,
    draining: Arc<AtomicBool>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        let readiness_draining = draining.clone();
        let router = Router::new()
            .route("/_liveness", get(|| async { "ok" }))
            .route(
                "/_readiness",
                get(move || readiness(readiness_draining.clone())),
            );
        let router = common_metrics::setup_metrics_routes_for_product_with_overrides(
            router,
            "cymbal-resolution",
            &[(
                common_metrics::Matcher::Full("cymbal_resolution_item_duration_ms".into()),
                ITEM_DURATION_BUCKETS_MS,
            )],
        );

        let bind = format!("0.0.0.0:{port}");
        tracing::info!("Metrics server listening on {}", bind);
        let listener = match tokio::net::TcpListener::bind(&bind).await {
            Ok(listener) => listener,
            Err(e) => {
                tracing::error!("Metrics server bind error: {e}");
                return;
            }
        };
        if let Err(e) = axum::serve(listener, router)
            .with_graceful_shutdown(wait_for_shutdown(shutdown_rx))
            .await
        {
            tracing::error!("Metrics server error: {e}");
        }
    })
}

fn spawn_shutdown_listener(
    shutdown_tx: watch::Sender<bool>,
    draining: Arc<AtomicBool>,
    load_monitor: LoadMonitor,
    drain_notice: Duration,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        shutdown_signal().await;
        tracing::info!(
            drain_notice_ms = drain_notice.as_millis() as u64,
            "shutdown signal received, marking cymbal-resolution as draining",
        );
        draining.store(true, Ordering::Relaxed);
        load_monitor.set_draining(true);
        tokio::time::sleep(drain_notice).await;
        tracing::info!("drain notice elapsed, stopping cymbal-resolution");
        let _ignored = shutdown_tx.send(true);
    })
}

async fn readiness(draining: Arc<AtomicBool>) -> (StatusCode, &'static str) {
    if draining.load(Ordering::Relaxed) {
        return (StatusCode::SERVICE_UNAVAILABLE, "draining");
    }

    (StatusCode::OK, "ok")
}

async fn wait_for_shutdown(mut shutdown_rx: watch::Receiver<bool>) {
    if *shutdown_rx.borrow() {
        return;
    }

    while shutdown_rx.changed().await.is_ok() {
        if *shutdown_rx.borrow() {
            return;
        }
    }
}

#[cfg(unix)]
async fn shutdown_signal() {
    use tokio::signal::unix::{signal, SignalKind};

    let mut sigterm = signal(SignalKind::terminate()).expect("failed to listen for SIGTERM");
    tokio::select! {
        result = tokio::signal::ctrl_c() => {
            if let Err(err) = result {
                tracing::warn!(error = %err, "failed to listen for Ctrl+C");
            }
        }
        _ = sigterm.recv() => {}
    }
}

#[cfg(not(unix))]
async fn shutdown_signal() {
    if let Err(err) = tokio::signal::ctrl_c().await {
        tracing::warn!(error = %err, "failed to listen for Ctrl+C");
    }
}
