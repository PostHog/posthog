use clap::Parser;

/// CLI config for local benchmark runs. Includes `--database-url` for convenience.
///
/// On Kubernetes, the benchmark runs via `flags-consumer benchmark` which reads
/// the database URL from `FLAGS_READ_STORE_DATABASE_URL` environment variable.
#[derive(Parser)]
#[command(
    name = "flags-gin-benchmark",
    about = "GIN index write-performance benchmark for the flags_person_lookup table"
)]
pub struct BenchmarkCliConfig {
    /// PostgreSQL connection string for the benchmark database.
    #[arg(long, env = "DATABASE_URL")]
    pub database_url: String,

    /// Total number of person rows to populate.
    #[arg(long, default_value = "100000")]
    pub scale: u64,

    /// Number of teams to spread data across.
    #[arg(long, default_value = "100")]
    pub teams: i32,

    /// Duration in seconds for each workload phase.
    #[arg(long, default_value = "60")]
    pub duration_secs: u64,

    /// Number of concurrent writer tasks per phase.
    #[arg(long, default_value = "4")]
    pub concurrency: usize,

    /// Concurrency multiplier for the burst merge storm phase.
    #[arg(long, default_value = "10")]
    pub burst_factor: usize,

    /// Batch size for batch_upsert_persons calls.
    #[arg(long, default_value = "500")]
    pub batch_size: usize,

    /// Skip data population (reuse existing table data).
    #[arg(long)]
    pub skip_populate: bool,
}
