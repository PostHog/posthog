use std::time::Duration;

use axum::{response::IntoResponse, routing::get, Router};
use lifecycle::{ComponentOptions, Manager};
use property_vals_rs::config::Config;
use serve_metrics::setup_metrics_routes;
use tokio::net::TcpListener;
use tracing::level_filters::LevelFilter;
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy()
            .add_directive("pyroscope=warn".parse().unwrap()),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "property-vals-rs"
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();
    info!("Starting up property-vals-rs...");

    let config = Config::init_with_defaults()?;

    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            warn!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

    let mut manager = Manager::builder("property-vals-rs")
        .with_global_shutdown_timeout(Duration::from_secs(60))
        .build();

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

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
    let app = setup_metrics_routes(app);

    let bind = format!("{}:{}", config.host, config.port);
    info!(address = %bind, "HTTP server starting");
    let listener = TcpListener::bind(&bind).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await?;
    metrics_handle.work_completed();

    info!("property-vals-rs stopped");
    Ok(())
}
