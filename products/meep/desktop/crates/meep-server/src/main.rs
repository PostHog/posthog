use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use meep_server::{DeviceTokens, Server};
use std::{net::SocketAddr, path::PathBuf};

#[derive(Parser)]
#[command(version, about)]
struct Cli {
    /// Server data and device credentials directory.
    #[arg(long, global = true, env = "MEEP_DATA_DIR")]
    data_dir: Option<PathBuf>,
    /// Address on which to accept HTTP connections.
    #[arg(
        long,
        global = true,
        default_value = "127.0.0.1:47950",
        env = "MEEP_LISTEN"
    )]
    listen: SocketAddr,
    /// Minimum diagnostic log level.
    #[arg(long, global = true, default_value = "info", env = "MEEP_LOG_LEVEL")]
    log_level: log::LevelFilter,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    /// Run the authoritative Topics service.
    Serve,
    /// Manage device credentials.
    #[command(alias = "token")]
    Device {
        #[command(subcommand)]
        command: Token,
    },
    /// Manage private user namespaces.
    Owner {
        #[command(subcommand)]
        command: Owner,
    },
}
#[derive(Subcommand)]
enum Owner {
    Add {
        #[arg(long)]
        label: Option<String>,
    },
    List,
}
#[derive(Subcommand)]
enum Token {
    /// Print a newly created device credential.
    #[command(alias = "create")]
    Add {
        #[arg(long)]
        owner: Option<uuid::Uuid>,
    },
    /// Revoke a device using its listed fingerprint.
    Revoke { fingerprint: String },
    /// Print the fingerprints of active device credentials.
    List,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    env_logger::Builder::new()
        .filter_level(cli.log_level)
        .init();
    let dir = match cli.data_dir {
        Some(p) => p,
        None => meep_server::data_dir()?,
    };
    match cli.command {
        Command::Serve => {
            let s = Server::open(dir).await?;
            let listener = tokio::net::TcpListener::bind(cli.listen)
                .await
                .context("Bind Topics HTTP listener")?;
            log::info!("Serving Topics at {}", listener.local_addr()?);
            #[cfg(unix)]
            let mut term =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
            s.serve(listener, async move {
                #[cfg(unix)]
                tokio::select! {_=tokio::signal::ctrl_c()=>{},_=term.recv()=>{}}
                #[cfg(not(unix))]
                let _ = tokio::signal::ctrl_c().await;
            })
            .await?;
        }
        Command::Owner { command } => {
            let tokens = DeviceTokens::open(dir)?;
            match command {
                Owner::Add { label } => println!("{}", tokens.add_owner(label)?),
                Owner::List => {
                    for (id, label) in tokens.owners()? {
                        println!("{}\t{}", id, label.unwrap_or_default());
                    }
                }
            }
        }
        Command::Device { command } => {
            let tokens = DeviceTokens::open(dir)?;
            match command {
                Token::Add { owner } => println!(
                    "{}",
                    match owner {
                        Some(id) => tokens.create_for(id)?,
                        None => tokens.create()?,
                    }
                ),
                Token::Revoke { fingerprint } => tokens.revoke(&fingerprint)?,
                Token::List => {
                    for id in tokens.list()? {
                        println!("{id}");
                    }
                }
            }
        }
    }
    Ok(())
}
