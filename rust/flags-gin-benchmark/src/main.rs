mod config;

use clap::Parser;
use flags_consumer::benchmark::BenchmarkArgs;

use crate::config::BenchmarkCliConfig;

/// Thin CLI wrapper for local development. Parses `--database-url` from the
/// command line and delegates to the benchmark implementation in `flags_consumer`.
///
/// On Kubernetes, the benchmark runs via the `flags-consumer benchmark` subcommand
/// directly, reading `FLAGS_READ_STORE_DATABASE_URL` from the environment.
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();

    let cli = BenchmarkCliConfig::parse();

    // Set the env var so the benchmark module can read it.
    std::env::set_var("FLAGS_READ_STORE_DATABASE_URL", &cli.database_url);

    let args = BenchmarkArgs {
        scale: cli.scale,
        teams: cli.teams,
        duration_secs: cli.duration_secs,
        concurrency: cli.concurrency,
        burst_factor: cli.burst_factor,
        batch_size: cli.batch_size,
        skip_populate: cli.skip_populate,
    };

    flags_consumer::benchmark::run(args).await
}
