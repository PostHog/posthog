use std::time::Duration;

use anyhow::{Context, Result};
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tokio::net::TcpListener;
use tracing::info;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use cohort_stream_processor::config::Config;
use cohort_stream_processor::observability;

common_alloc::used!();

const SERVICE_NAME: &str = "cohort-stream-processor";

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
    init_tracing();

    info!(service = SERVICE_NAME, ?config, "starting service");

    // The lifecycle manager owns signal trapping, graceful-shutdown coordination, and the
    // readiness/liveness probes. The skeleton registers only the observability server; the
    // consumers, partition workers, sweep, and checkpoint tasks (TDD §2.3) are registered
    // here as Phase 1–3 PRs build them out. The generous shutdown timeout leaves room for
    // the final RocksDB checkpoint flush a stateful worker needs on drain.
    let mut manager = Manager::builder(SERVICE_NAME)
        .with_global_shutdown_timeout(Duration::from_secs(90))
        .build();

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let recorder_handle = if config.export_prometheus {
        Some(observability::metrics::install_recorder())
    } else {
        None
    };

    let guard = manager.monitor_background();

    let app = observability::health::router(SERVICE_NAME, readiness, liveness, recorder_handle);

    let bind = config.bind_address();
    info!(address = %bind, "observability server starting");

    let listener = TcpListener::bind(&bind)
        .await
        .with_context(|| format!("failed to bind observability server to {bind}"))?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await
        .context("observability server error")?;
    metrics_handle.work_completed();

    guard.wait().await?;

    info!(service = SERVICE_NAME, "service stopped");
    Ok(())
}

/// JSON structured logging in production; human-readable when `RUST_LOG` requests debug.
/// Mirrors `rust/ingestion-consumer/src/main.rs`.
fn init_tracing() {
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
}
