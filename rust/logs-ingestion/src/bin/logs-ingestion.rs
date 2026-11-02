//! The logs (or traces) ingestion Kafka consumer. See `README.md` for primary and shadow mode.

use logs_ingestion::service::{self, config::ServiceConfig, node_env::process_env};
use tracing_subscriber::EnvFilter;

common_alloc::used!();

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();
    let config = ServiceConfig::from_env(&process_env())?;
    service::run(config).await
}
