mod collector;
mod collectors;
mod config;
mod http;
mod logs;
mod pg;
mod scheduler;
mod sink;

use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
use std::sync::Arc;
use tracing_subscriber::EnvFilter;

#[derive(Parser, Debug)]
#[command(name = "pgcollector", about = "Postgres telemetry collector")]
struct Cli {
    /// Path to pgcollector.toml
    #[arg(
        short,
        long,
        env = "PGCOLLECTOR_CONFIG",
        default_value = "pgcollector.toml"
    )]
    config: PathBuf,
    /// Optional overlay directory of YAML collectors (defaults are compiled in)
    #[arg(long, env = "PGCOLLECTOR_COLLECTORS_DIR")]
    collectors_dir: Option<PathBuf>,
    /// Validate config + collectors and exit
    #[arg(long)]
    check: bool,
    /// Run every collector once against every server, print row counts, exit (no sink writes)
    #[arg(long)]
    once: bool,
    /// Parse a Postgres log file with --log-line-prefix and print what was classified, then exit
    #[arg(long)]
    parse_log: Option<PathBuf>,
    #[arg(long, default_value = "%t:%r:%u@%d:[%p]:")]
    log_line_prefix: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| "info,tokio_postgres=warn".into()),
        )
        .init();

    let cli = Cli::parse();
    if let Some(path) = &cli.parse_log {
        return parse_log(path, &cli.log_line_prefix);
    }
    let cfg = config::Config::load(&cli.config)?;
    let registry = collectors::Registry::load(cli.collectors_dir.as_deref())?;
    tracing::info!(
        servers = cfg.servers.len(),
        collectors = registry.len(),
        "loaded config"
    );

    if cli.check {
        for c in registry.iter() {
            let r = c.requires();
            let req = match (r.aurora, &r.extension) {
                (true, Some(e)) => format!("aurora, ext:{e}"),
                (true, None) => "aurora".into(),
                (false, Some(e)) => format!("ext:{e}"),
                _ => String::new(),
            };
            let off = if c.default_enabled() {
                ""
            } else {
                "[off by default] "
            };
            println!(
                "{:<24} {:<9} {:>6}s  pg>={}  per_instance={:<5} {req:<28} {off}{}",
                c.name(),
                format!("{:?}", c.scope()),
                c.interval().as_secs(),
                c.min_pg_version(),
                c.per_instance(),
                c.description()
            );
        }
        for s in &cfg.servers {
            println!(
                "server {:<16} instances={:?} databases={:?}",
                s.id,
                s.instances.keys().collect::<Vec<_>>(),
                cfg.databases_for(s)
            );
        }
        return Ok(());
    }

    let sink: Arc<dyn sink::Sink> = if cli.once {
        Arc::new(sink::StdoutSink)
    } else {
        Arc::new(sink::postgres::PostgresSink::connect(&cfg.sink).await?)
    };

    let ready = http::Readiness::default();
    if !cli.once {
        let (listen, ready) = (cfg.http.listen.clone(), ready.clone());
        tokio::spawn(async move {
            if let Err(e) = http::serve(listen, ready).await {
                tracing::error!(error = %e, "http server exited");
            }
        });
    }

    scheduler::run(Arc::new(cfg), Arc::new(registry), sink, ready, cli.once).await
}

fn parse_log(path: &std::path::Path, prefix: &str) -> Result<()> {
    use logs::parse::*;
    let re = prefix_regex(prefix);
    let text = std::fs::read_to_string(path)?;
    let mut asm = Assembler::default();
    let mut counts: std::collections::BTreeMap<String, usize> = Default::default();
    let mut unparsed = 0usize;
    let mut entries = Vec::new();
    for line in text.lines() {
        if !line.starts_with('\t') && !re.is_match(line) {
            unparsed += 1;
        }
        if let Some(e) = asm.push(&re, line) {
            entries.push(e);
        }
    }
    if let Some(e) = asm.flush() {
        entries.push(e);
    }
    for e in &entries {
        let name = match classify(e) {
            Record::Duration { .. } => "duration",
            Record::Plan { .. } => "plan",
            Record::Autovacuum(_) => "autovacuum",
            Record::Checkpoint(_) => "checkpoint",
            Record::LockWait { .. } => "lock_wait",
            Record::Deadlock => "deadlock",
            Record::TempFile { .. } => "temp_file",
            Record::Cancel { .. } => "cancel",
            Record::Connection { .. } => "connection",
            Record::Error => "error",
            Record::Other => "other",
        };
        *counts.entry(format!("{:<7} {name}", e.level)).or_default() += 1;
    }
    println!(
        "entries: {}   lines not matching prefix (treated as continuation): {}",
        entries.len(),
        unparsed
    );
    for (k, v) in counts {
        println!("{v:>8}  {k}");
    }
    for e in entries
        .iter()
        .filter(|e| matches!(classify(e), Record::Other))
        .take(5)
    {
        println!("other: {}", e.message.lines().next().unwrap_or(""));
    }
    Ok(())
}
