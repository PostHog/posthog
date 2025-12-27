use anyhow::{Context, Result};
use axum::{routing::get, Router};
use futures::future::ready;
use health::HealthRegistry;
use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};
use serve_metrics::serve;
use tokio::task::JoinHandle;
use tracing::{error, info};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use repartitioner::{config::Config, service::RepartitionerService};

fn setup_metrics() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("Failed to install metrics recorder")
}

fn start_server(config: &Config, liveness: HealthRegistry) -> JoinHandle<()> {
    let router = Router::new()
        .route("/", get(|| async { "repartitioner service" }))
        .route("/_readiness", get(|| async { "ok" }))
        .route(
            "/_liveness",
            get(move || {
                let liveness = liveness.clone();
                async move {
                    let status = liveness.get_status();
                    if !status.healthy {
                        let unhealthy_components: Vec<String> = status
                            .components
                            .iter()
                            .filter(|(_, component_status)| !component_status.is_healthy())
                            .map(|(name, component_status)| format!("{name}: {component_status:?}"))
                            .collect();
                        error!(
                            "Health check FAILED - unhealthy components: [{}]",
                            unhealthy_components.join(", ")
                        );
                    }
                    status
                }
            }),
        );

    let router = if config.export_prometheus {
        let recorder_handle = setup_metrics();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    };

    let bind = config.bind_address.clone();

    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

#[tokio::main]
async fn main() -> Result<()> {
    let config = Config::init_with_defaults()
        .context("Failed to load configuration from environment variables")?;

    // Initialize tracing
    let log_layer = fmt::layer()
        .with_target(true)
        .with_thread_ids(true)
        .with_level(true)
        .with_filter(EnvFilter::from_default_env())
        .boxed();

    tracing_subscriber::registry().with(log_layer).init();

    info!("Starting Repartitioner service");
    info!("Configuration loaded: {:?}", config);

    // Create health registry
    let liveness = HealthRegistry::new("liveness");

    // Start HTTP server with metrics endpoint
    let server_handle = start_server(&config, liveness.clone());
    info!("Started metrics server on {}", config.bind_address);

    // Create and run the service
    let service = RepartitionerService::new(config, liveness)
        .await
        .context("Failed to create Repartitioner service")?;

    // Run the service (this blocks until shutdown)
    service.run().await?;

    // Clean up metrics server
    server_handle.abort();

    Ok(())
}
