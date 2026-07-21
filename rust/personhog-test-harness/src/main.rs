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

use cli::{Cli, Command};

#[tokio::main]
async fn main() -> Result<()> {
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
    }
}
