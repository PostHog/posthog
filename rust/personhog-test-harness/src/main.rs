use anyhow::Result;
use clap::Parser;
use tracing_subscriber::EnvFilter;

mod cli;
mod client;
mod report;
mod scenarios;
mod seed;
mod stack;
mod state;
mod stats;
mod traffic_metrics;
mod verify;

use cli::{Cli, Command};

#[tokio::main]
async fn main() -> Result<()> {
    // Install a process-wide rustls CryptoProvider before any TLS use.
    // kube's client resolves it lazily, so without this the first chaos
    // scenario's Kubernetes API call panics its worker while plaintext
    // traffic carries on — chaos dies silently. Mirrors the leader and
    // router mains.
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("failed to install rustls ring CryptoProvider");

    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("personhog_test_harness=info,warn")),
        )
        .init();

    let cli = Cli::parse();
    match cli.command {
        Command::Seed(args) => scenarios::seed_cmd::run(args).await,
        Command::Cleanup(args) => scenarios::seed_cmd::run_cleanup(args).await,
        Command::Blast(args) => scenarios::blast::run(args).await,
        Command::Consistency(args) => scenarios::consistency::run(args).await,
        Command::Gate(args) => scenarios::gate::run(*args).await,
        Command::Traffic(args) => scenarios::traffic::run(*args).await,
    }
}
