use logs_ingestion::service::{self, config::ServiceConfig, node_env::process_env};
use tracing_subscriber::EnvFilter;

common_alloc::used!();

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
    service::run(config).await
}
