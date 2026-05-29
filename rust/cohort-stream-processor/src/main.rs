use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tokio::net::TcpListener;
use tracing::{info, warn};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use cohort_stream_processor::config::Config;
use cohort_stream_processor::filters::{run_refresh_loop, CatalogHandle};
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
    log_startup(&config);

    // The lifecycle manager owns signal trapping, graceful-shutdown coordination, and the
    // readiness/liveness probes. PR 1.3 registers the observability server and the filter
    // catalog refresh task; the consumers, partition workers, sweep, and checkpoint tasks
    // (TDD §2.3) are registered here as Phase 1–3 PRs build them out. The generous shutdown
    // timeout leaves room for the final RocksDB checkpoint flush a stateful worker needs.
    let mut manager = Manager::builder(SERVICE_NAME)
        .with_global_shutdown_timeout(Duration::from_secs(90))
        .build();

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));
    // The catalog refresh task is monitored only for clean shutdown, not liveness: a refresh
    // outage must not kill the service (it keeps serving the last good snapshot — staleness is
    // safe, §2.7). An unexpected exit still signals the manager via the process-scope guard.
    let catalog_handle_lifecycle = manager.register(
        "filter-catalog",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let recorder_handle = if config.export_prometheus {
        Some(observability::metrics::install_recorder())
    } else {
        None
    };

    // Build all infrastructure before starting the monitor. A startup failure here returns
    // before the monitor thread is running, so the dropped handles are harmless no-ops and the
    // process exits non-zero for K8s to restart.
    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating posthog_cohort database pool")?;

    let catalog = Arc::new(CatalogHandle::new());
    match catalog.refresh(&pool).await {
        Ok(stats) => info!(
            teams = stats.teams,
            unique_conditions = stats.unique_conditions,
            "initial filter catalog loaded",
        ),
        Err(err) => warn!(
            error = %err,
            "initial filter catalog load failed; catalog is empty until the refresh task succeeds",
        ),
    }

    let guard = manager.monitor_background();

    // Filter catalog refresh loop.
    let refresh_catalog = catalog.clone();
    let refresh_pool = pool.clone();
    let refresh_interval = config.filter_catalog_refresh_interval();
    let refresh_jitter = config.filter_catalog_refresh_jitter();
    tokio::spawn(async move {
        run_refresh_loop(
            refresh_catalog,
            refresh_pool,
            refresh_interval,
            refresh_jitter,
            catalog_handle_lifecycle,
        )
        .await;
    });

    // Observability server (runs until graceful shutdown begins).
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

/// Log a redacted startup summary. Deliberately omits `database_url` (carries credentials).
fn log_startup(config: &Config) {
    info!(
        service = SERVICE_NAME,
        bind_address = %config.bind_address(),
        filter_catalog_refresh_secs = config.filter_catalog_refresh_secs,
        filter_catalog_refresh_jitter_secs = config.filter_catalog_refresh_jitter_secs,
        "starting cohort-stream-processor",
    );
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
