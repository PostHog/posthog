use std::time::Duration;

use axum::{routing::get, routing::post, Router};
use capture::metrics_middleware::track_metrics;
use common_metrics::{serve, setup_metrics_routes};
use log_capture::config::Config;
use log_capture::kafka::KafkaSink;
use log_capture::service::export_logs_http;
use log_capture::service::Service;
use std::future::ready;

use health::HealthRegistry;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

fn setup_tracing() {
    let log_layer: tracing_subscriber::filter::Filtered<
        tracing_subscriber::fmt::Layer<tracing_subscriber::Registry>,
        EnvFilter,
        tracing_subscriber::Registry,
    > = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "log hog hogs logs

.|||||||||.
|||||||||||||  gimme ur logs 🔫
|||||||||||' .\\
`||||||||||_,__o
"
}

#[tokio::main]
async fn main() {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults().unwrap();
    let health_registry = HealthRegistry::new("liveness");

    let sink_liveness = health_registry
        .register("rdkafka".to_string(), Duration::from_secs(30))
        .await;

    let kafka_sink = KafkaSink::new(config.kafka.clone(), sink_liveness)
        .await
        .expect("failed to start Kafka sink");

    let management_router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(health_registry.get_status())),
        );
    let management_router = setup_metrics_routes(management_router);
    let management_bind = format!("{}:{}", config.management_host, config.management_port);
    info!("Healthcheck and metrics listening on {}", management_bind);

    let logs_service = match Service::new(kafka_sink).await {
        Ok(service) => service,
        Err(e) => {
            error!("Failed to initialize log service: {}", e);
            panic!("Could not start log capture service: {e}");
        }
    };
    let http_bind = format!("{}:{}", config.host, config.port);
    info!("Listening on {}", http_bind);

    let http_router = Router::new()
        .route("/v1/logs", post(export_logs_http))
        .route("/i/v1/logs", post(export_logs_http))
        .with_state(logs_service)
        .layer(axum::middleware::from_fn(track_metrics));

    let http_server = tokio::spawn(async move {
        if let Err(e) = serve(http_router, &http_bind).await {
            error!("HTTP server failed: {}", e);
        }
    });

    let mgmt_server = tokio::spawn(async move {
        if let Err(e) = serve(management_router, &management_bind).await {
            error!("Management server failed: {}", e);
        }
    });

    // Wait for any server to finish
    tokio::select! {
        _ = http_server => {
            error!("HTTP server stopped unexpectedly");
        }
        _ = mgmt_server => {
            error!("Management server stopped unexpectedly");
        }
    }
}
