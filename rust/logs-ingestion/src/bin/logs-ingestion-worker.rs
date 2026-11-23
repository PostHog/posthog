//! The logs pipeline as a gRPC worker of the Rust `ingestion-consumer`. It reads the same env as `logs-ingestion`, except the Kafka consumer keys, which the consumer owns.

use logs_ingestion::service::{self, config::ServiceConfig, node_env::process_env};
use tracing_subscriber::EnvFilter;

common_alloc::used!();

fn env_number<T: std::str::FromStr>(name: &str, default: T) -> anyhow::Result<T> {
    match std::env::var(name) {
        Ok(value) => value
            .parse()
            .map_err(|_| anyhow::anyhow!("{name} is not a valid number: {value:?}")),
        Err(_) => Ok(default),
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Both aws-lc-rs and ring are in the dependency graph, so rustls cannot pick a provider and panics on the first TLS connection.
    rustls::crypto::aws_lc_rs::default_provider()
        .install_default()
        .expect("failed to install the rustls CryptoProvider");
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();
    let config = ServiceConfig::from_env(&process_env())?;
    // The names the Node ingestion-api worker and the consumer use for the same settings.
    let grpc_port = env_number("INGESTION_API_GRPC_PORT", 6739)?;
    let concurrent_batches = env_number("INGESTION_WORKER_CONCURRENT_BATCHES", 1)?;
    service::run_worker(config, grpc_port, concurrent_batches).await
}
