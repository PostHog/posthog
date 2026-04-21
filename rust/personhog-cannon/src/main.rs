mod chaos;
mod cli;
mod client;
mod report;
mod scenarios;
mod state;
mod stats;

use clap::Parser;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "personhog_cannon=info".into()),
        )
        .init();

    let cli = cli::Cli::parse();

    match cli.command {
        cli::Command::Discover(args) => {
            let client = client::CannonClient::connect(&cli.router_url).await?;
            scenarios::discover::run(client, args).await
        }
        cli::Command::Blast(args) => {
            let client = client::CannonClient::connect(&cli.router_url).await?;
            scenarios::blast::run(client, args).await
        }
        cli::Command::Consistency(args) => {
            let client = client::CannonClient::connect(&cli.router_url).await?;
            scenarios::consistency::run(client, args).await
        }
        cli::Command::Chaos(chaos_args) => match chaos_args.command {
            cli::ChaosCommand::Status(args) => chaos::status::run(args).await,
            cli::ChaosCommand::Kill(args) => chaos::kill::run(args).await,
            cli::ChaosCommand::Shutdown(args) => chaos::shutdown::run(args).await,
            cli::ChaosCommand::ScaleUp(args) => chaos::scale_up::run(args).await,
            cli::ChaosCommand::Run(args) => {
                let client = client::CannonClient::connect(&cli.router_url).await?;
                chaos::run::run(client, args).await
            }
        },
    }
}
