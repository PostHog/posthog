use opentelemetry_proto::tonic::collector::logs::v1::logs_service_server::LogsServiceServer;
use std::net::SocketAddr;
use tonic::transport::Server;

use axum::{routing::get, Router};
use common_metrics::{serve, setup_metrics_routes};
use log_capture::config::Config;
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

    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(health_registry.get_status())),
        );
    let router = setup_metrics_routes(router);
    let bind = format!("{}:{}", config.host, config.port);
    info!("Healthcheck listening on {}", bind);
    let server = serve(router, &bind);

    let addr = SocketAddr::from(([0, 0, 0, 0], 4317)); // Standard OTLP gRPC port

    // Initialize ClickHouse writer and logs service
    let logs_service = match Service::new(config).await {
        Ok(service) => service,
        Err(e) => {
            error!("Failed to initialize log service: {}", e);
            panic!("Could not start log capture service: {}", e);
        }
    };

    Server::builder()
        .add_service(LogsServiceServer::new(logs_service))
        .serve(addr)
        .await
        .unwrap();

    server.await.unwrap();
}
