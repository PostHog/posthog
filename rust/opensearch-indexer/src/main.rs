use std::sync::Arc;
use std::time::Duration;

use opensearch_indexer::{api::root_router, app_context::AppContext, config::Config};
use serve_metrics::setup_metrics_routes;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use tracing::level_filters::LevelFilter;
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy(),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    setup_tracing();
    info!("Starting opensearch-indexer...");

    let config = Config::init_with_defaults()?;
    let bind = format!("{}:{}", config.host, config.port);

    let context = Arc::new(AppContext::new(config).await?);

    info!(
        "Subscribed to topic: {}",
        context.config.consumer.kafka_consumer_topic
    );

    let shutdown = CancellationToken::new();

    // Stage A placeholder: keep the indexer health component fresh until Stage B's
    // work loop takes over reporting. The HealthHandle deadline is 60s; we tick
    // well inside that.
    let heartbeat_ctx = context.clone();
    let heartbeat_shutdown = shutdown.clone();
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(Duration::from_secs(15));
        loop {
            tokio::select! {
                _ = ticker.tick() => heartbeat_ctx.indexer_handle.report_healthy().await,
                _ = heartbeat_shutdown.cancelled() => break,
            }
        }
    });

    let app = root_router(context.liveness.clone());
    let app = setup_metrics_routes(app);

    info!(address = %bind, "HTTP server starting");
    let listener = TcpListener::bind(&bind).await?;

    let server_shutdown = shutdown.clone();
    let server = tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                server_shutdown.cancelled().await;
            })
            .await
        {
            warn!("HTTP server exited with error: {e}");
        }
    });

    // Stage A: no work loop yet. Just wait for SIGINT/SIGTERM and exit.
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {
            info!("Received SIGINT, shutting down");
        }
        _ = wait_for_sigterm() => {
            info!("Received SIGTERM, shutting down");
        }
    }

    shutdown.cancel();
    if let Err(e) = server.await {
        warn!("HTTP server task join error: {e}");
    }

    info!("opensearch-indexer stopped");
    Ok(())
}

#[cfg(unix)]
async fn wait_for_sigterm() {
    use tokio::signal::unix::{signal, SignalKind};
    if let Ok(mut term) = signal(SignalKind::terminate()) {
        term.recv().await;
    } else {
        std::future::pending::<()>().await;
    }
}

#[cfg(not(unix))]
async fn wait_for_sigterm() {
    std::future::pending::<()>().await;
}
