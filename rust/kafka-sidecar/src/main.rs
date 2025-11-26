use health::HealthRegistry;
use kafka_sidecar::config::Config;
use kafka_sidecar::proto::kafka_producer::kafka_producer_server::KafkaProducerServer;
use kafka_sidecar::service::KafkaProducerService;
use metrics_exporter_prometheus::PrometheusBuilder;
use std::net::SocketAddr;
use std::time::Duration;
use tonic::transport::Server;
use tonic_health::server::health_reporter;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "kafka_sidecar=debug,info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    info!("Kafka gRPC sidecar starting...");

    // Load configuration
    let config = Config::from_env()?;
    info!("Configuration loaded: {:?}", config);

    // Set up health registry
    let health_registry = HealthRegistry::new("liveness");
    let kafka_liveness = health_registry
        .register("kafka".to_string(), Duration::from_secs(30))
        .await;

    // Initialize Prometheus metrics exporter
    let metrics_addr: SocketAddr = format!("0.0.0.0:{}", config.metrics_port).parse()?;
    PrometheusBuilder::new()
        .with_http_listener(metrics_addr)
        .install()?;
    info!("Metrics server listening on {}", metrics_addr);

    // Create Kafka producer
    info!("Connecting to Kafka at {}...", config.kafka_hosts);
    let kafka_config = config.to_kafka_config();
    let producer =
        common_kafka::kafka_producer::create_kafka_producer(&kafka_config, kafka_liveness)
            .await
            .map_err(|e| {
                error!("Failed to create Kafka producer: {}", e);
                e
            })?;
    info!("Successfully connected to Kafka");

    // Set up gRPC health reporting
    let (mut health_reporter, health_service) = health_reporter();

    // Set the kafka producer service as serving
    health_reporter
        .set_serving::<KafkaProducerServer<KafkaProducerService>>()
        .await;

    // Spawn a task to monitor Kafka health and update gRPC health status
    let health_registry_clone = health_registry.clone();
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(5)).await;
            let status = health_registry_clone.get_status();

            if status.healthy {
                health_reporter
                    .set_serving::<KafkaProducerServer<KafkaProducerService>>()
                    .await;
            } else {
                health_reporter
                    .set_not_serving::<KafkaProducerServer<KafkaProducerService>>()
                    .await;
                error!("Kafka health check failed, marking gRPC service as not serving");
            }
        }
    });

    // Create gRPC service
    let kafka_service = KafkaProducerService::new(producer);
    let grpc_addr: SocketAddr = format!("0.0.0.0:{}", config.grpc_port).parse()?;

    info!("gRPC server listening on {}", grpc_addr);
    info!("gRPC health check available at grpc.health.v1.Health/Check");

    // Start gRPC server with both services
    Server::builder()
        .add_service(health_service)
        .add_service(KafkaProducerServer::new(kafka_service))
        .serve(grpc_addr)
        .await?;

    Ok(())
}
