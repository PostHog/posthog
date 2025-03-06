pub mod auth;
use clap::{Parser, Subcommand};

use crate::error::CapturedError;

#[derive(Parser)]
#[command(version, about, long_about = None)]
pub struct Cli {
    /// The PostHog host to connect to
    #[arg(long, default_value = "https://us.posthog.com")]
    host: String,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Authenticate with PostHog, storing a personal API token locally
    Login,
}

impl Cli {
    pub fn run() -> Result<(), CapturedError> {
        let command = Cli::parse();

        match &command.command {
            Commands::Login => {
                auth::login()?;
            }
        }

        Ok(())
    }
}
