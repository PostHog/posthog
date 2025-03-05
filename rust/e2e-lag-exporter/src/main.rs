mod config;
mod kafka;
mod metrics;

use anyhow::{Context, Result};
use config::Config;
use envconfig::Envconfig;
use kafka::KafkaMonitor;
use metrics_exporter_prometheus::PrometheusBuilder;
use std::net::SocketAddr;
use tokio::time;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<()> {
    // Load configuration from environment variables
    let config = Config::init_from_env().context("Failed to load configuration")?;

    // Setup tracing
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .with_max_level(config.log_level)
        .init();

    info!("Starting e2e-lag-exporter with config: {:?}", config);

    // Register metrics
    metrics::register_metrics();

    // Setup Prometheus metrics exporter
    let metrics_addr = format!("0.0.0.0:{}", config.metrics_port).parse::<SocketAddr>()?;
    PrometheusBuilder::new()
        .with_http_listener(metrics_addr)
        .install()
        .context("Failed to install Prometheus metrics exporter")?;

    info!("Metrics server listening on {}", metrics_addr);

    // Create Kafka monitor
    let kafka_monitor =
        KafkaMonitor::new(config.clone()).context("Failed to create Kafka monitor")?;

    info!("Monitoring consumer group: {}", config.kafka_consumer_group);

    // Main loop: check lag at configured intervals
    let mut interval = time::interval(config.lag_check_interval());
    loop {
        interval.tick().await;

        match kafka_monitor.check_lag().await {
            Ok(_) => {
                info!("Successfully checked consumer lag");
            }
            Err(e) => {
                error!("Error checking consumer lag: {:?}", e);
            }
        }
    }
}
