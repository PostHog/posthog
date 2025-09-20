use opentelemetry_proto::tonic::collector::logs::v1::logs_service_server::LogsServiceServer;
use opentelemetry_proto::tonic::collector::trace::v1::trace_service_server::TraceServiceServer;
use std::time::Duration;
use tonic_web::GrpcWebLayer;
use tower::Layer as TowerLayer;

use axum::routing::get;
use common_metrics::{serve, setup_metrics_routes};
use log_capture::config::Config;
use log_capture::kafka::KafkaSink;
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

    let bind = format!("{}:{}", config.host, config.port);

    // Initialize ClickHouse writer and logs service
    let logs_service = match Service::new(config.clone(), kafka_sink).await {
        Ok(service) => service,
        Err(e) => {
            error!("Failed to initialize log service: {}", e);
            panic!("Could not start log capture service: {e}");
        }
    };

    let router = tonic::service::Routes::new(GrpcWebLayer::new().layer(tonic_web::enable(
        LogsServiceServer::new(logs_service.clone()),
    )))
    .add_service(tonic_web::enable(TraceServiceServer::new(logs_service)))
    .prepare()
    .into_axum_router()
    .route("/", get(index))
    .route("/_readiness", get(index))
    .route(
        "/_liveness",
        get(move || ready(health_registry.get_status())),
    );
    let router = setup_metrics_routes(router);

    serve(router, &bind).await.unwrap();
}
