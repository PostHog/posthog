pub mod auth;
pub mod inject;
use std::path::PathBuf;
pub mod sourcemap_upload;
use clap::{Parser, Subcommand};
use tracing::info;

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

    #[command(about = "Upload a directory of bundled chunks to PostHog")]
    Sourcemap {
        #[command(subcommand)]
        cmd: SourcemapCommand,
    },
}

#[derive(Subcommand)]
pub enum SourcemapCommand {
    /// Inject each bundled chunk with a posthog chunk ID
    Inject {
        /// The directory containing the bundled chunks
        #[arg(short, long)]
        directory: PathBuf,

        /// Where to write the injected chunks. If not provided, the original files will be overwritten
        #[arg(short, long)]
        output: Option<String>,
    },
    /// Upload the bundled chunks to PostHog
    Upload {
        /// The directory containing the bundled chunks
        #[arg(short, long)]
        directory: PathBuf,

        /// The build ID to associate with the uploaded chunks
        #[arg(short, long)]
        build: Option<String>,
    },
}

impl Cli {
    pub fn run() -> Result<(), CapturedError> {
        let command = Cli::parse();

        match &command.command {
            Commands::Login => {
                auth::login()?;
            }
            Commands::Sourcemap { cmd } => match cmd {
                SourcemapCommand::Inject {
                    directory: dir,
                    output: _,
                } => {
                    inject::process_directory(dir)
                        .map_err(|e| e.context("Failed to inject sourcemaps"))?;
                    info!("Successfully injected sourcemaps");
                }
                SourcemapCommand::Upload { directory, build } => {
                    sourcemap_upload::upload(&command.host, directory, build)?;
                }
            },
        }

        Ok(())
    }
}
