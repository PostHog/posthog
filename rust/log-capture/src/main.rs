use opentelemetry_proto::tonic::collector::logs::v1::logs_service_server::LogsServiceServer;
use opentelemetry_proto::tonic::collector::trace::v1::trace_service_server::TraceServiceServer;
use tonic_web::GrpcWebLayer;
use tower::Layer as TowerLayer;

use axum::routing::get;
use common_metrics::{serve, setup_metrics_routes};
use log_capture::config::Config;
use log_capture::http_handler::create_http_router;
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

    // Initialize service once
    let service = match Service::new(config.clone()).await {
        Ok(service) => service,
        Err(e) => {
            error!("Failed to initialize log service: {}", e);
            panic!("Could not start log capture service: {}", e);
        }
    };

    // Clone service for different servers
    let grpc_service = service.clone();
    let http_service = service.clone();

    // gRPC server setup (OTLP logs and traces, no management endpoints)
    let grpc_bind = config.grpc_bind_address();
    let grpc_router = tonic::service::Routes::new(GrpcWebLayer::new().layer(tonic_web::enable(
        LogsServiceServer::new(grpc_service.clone()),
    )))
    .add_service(tonic_web::enable(TraceServiceServer::new(grpc_service)))
    .prepare()
    .into_axum_router();

    // HTTP server setup (OTLP only, no management endpoints)
    let http_bind = config.http_bind_address();
    let http_router = create_http_router(http_service);

    // Management server setup (health checks, metrics, info)
    let mgmt_bind = config.mgmt_bind_address();
    let mgmt_router = axum::Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(health_registry.get_status())),
        );
    let mgmt_router = setup_metrics_routes(mgmt_router);

    info!("Starting gRPC server on {}", grpc_bind);
    info!("Starting HTTP server on {}", http_bind);
    info!("Starting management server on {}", mgmt_bind);

    // Start all three servers concurrently
    let grpc_server = tokio::spawn(async move {
        if let Err(e) = serve(grpc_router, &grpc_bind).await {
            error!("gRPC server failed: {}", e);
        }
    });

    let http_server = tokio::spawn(async move {
        if let Err(e) = serve(http_router, &http_bind).await {
            error!("HTTP server failed: {}", e);
        }
    });

    let mgmt_server = tokio::spawn(async move {
        if let Err(e) = serve(mgmt_router, &mgmt_bind).await {
            error!("Management server failed: {}", e);
        }
    });

    // Wait for any server to finish (or all)
    tokio::select! {
        _ = grpc_server => {
            error!("gRPC server stopped unexpectedly");
        }
        _ = http_server => {
            error!("HTTP server stopped unexpectedly");
        }
        _ = mgmt_server => {
            error!("Management server stopped unexpectedly");
        }
    }
}