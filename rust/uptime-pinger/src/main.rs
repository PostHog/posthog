use std::sync::Arc;
use std::time::Duration;

use axum::{response::IntoResponse, routing::get, Router};
use lifecycle::{ComponentOptions, Manager};
use tokio::net::TcpListener;
use tracing::{info, level_filters::LevelFilter, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

use uptime_pinger::app_context::AppContext;
use uptime_pinger::config::Config;
use uptime_pinger::worker::run_worker_loop;

common_alloc::used!();

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy(),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

async fn index() -> &'static str {
    "uptime-pinger"
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();
    info!("Starting up uptime-pinger service...");

    let config = Config::init_with_defaults()?;

    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            warn!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

    let mut manager = Manager::builder("uptime-pinger")
        .with_global_shutdown_timeout(Duration::from_secs(60))
        .build();

    let worker_handle = manager.register(
        "worker",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(Duration::from_secs(120)),
    );

    let kafka_handle = manager.register("kafka", ComponentOptions::new());

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let context = Arc::new(AppContext::new(config.clone(), kafka_handle.clone()).await?);
    info!(
        "Producing pings to topic '{}'",
        context.config.kafka_pings_topic
    );

    let guard = manager.monitor_background();

    let worker_ctx = Arc::clone(&context);
    let wh = worker_handle.clone();
    tokio::spawn(async move {
        run_worker_loop(worker_ctx, wh).await;
    });
    drop(worker_handle);

    let app = Router::new()
        .route("/", get(index))
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

    let bind = format!("{}:{}", context.config.host, context.config.port);
    info!(address = %bind, "HTTP server starting");
    let listener = TcpListener::bind(&bind).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await?;
    metrics_handle.work_completed();

    guard.wait().await?;

    info!("uptime-pinger stopped");
    Ok(())
}
