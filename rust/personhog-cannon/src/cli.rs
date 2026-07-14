use std::time::Duration;

use clap::{Args, Parser, Subcommand};

pub const DEFAULT_PERSONS_DB_URL: &str =
    "postgres://posthog:posthog@localhost:5432/posthog_persons";

/// The dev-stack leader-mode router (bin/mprocs.yaml `personhog-router-leader`).
pub const DEV_STACK_ROUTER_URL: &str = "http://127.0.0.1:50054";

#[derive(Parser)]
#[command(
    name = "personhog-cannon",
    about = "Load, consistency, and e2e correctness harness for the personhog leader path"
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Subcommand)]
pub enum Command {
    /// Seed persons directly into Postgres for use as traffic targets.
    Seed(SeedArgs),
    /// Delete all harness data for a team from Postgres.
    Cleanup(CleanupArgs),
    /// High-throughput concurrent property updates with read-back verification.
    Blast(BlastArgs),
    /// Write-then-strong-read consistency validation.
    Consistency(ConsistencyArgs),
    /// Full e2e gate: stack up, seed, traffic, quiesce, verify, cleanup.
    Gate(GateArgs),
}

#[derive(Args, Clone)]
pub struct SeedArgs {
    #[arg(long)]
    pub team_id: i64,

    /// Number of persons to create.
    #[arg(long, default_value_t = 100)]
    pub count: u32,

    #[arg(long, default_value = DEFAULT_PERSONS_DB_URL)]
    pub persons_db_url: String,
}

#[derive(Args, Clone)]
pub struct CleanupArgs {
    #[arg(long)]
    pub team_id: i64,

    #[arg(long, default_value = DEFAULT_PERSONS_DB_URL)]
    pub persons_db_url: String,
}

#[derive(Args, Clone)]
pub struct BlastArgs {
    #[arg(long, default_value = DEV_STACK_ROUTER_URL)]
    pub router_url: String,

    #[arg(long)]
    pub team_id: i64,

    /// Person IDs to target (comma-separated). Use `seed` to create targets.
    #[arg(long, value_delimiter = ',', required = true)]
    pub person_ids: Vec<i64>,

    #[arg(long, default_value_t = 10)]
    pub concurrency: usize,

    #[arg(long, value_parser = humantime::parse_duration)]
    pub duration: Duration,

    /// Prefix for generated property keys.
    #[arg(long, default_value = "cannon_")]
    pub property_prefix: String,

    /// Read back each person with STRONG consistency after the blast and
    /// verify that every acked write is present.
    #[arg(long, default_value_t = true, action = clap::ArgAction::Set)]
    pub verify: bool,
}

#[derive(Args, Clone)]
pub struct ConsistencyArgs {
    #[arg(long, default_value = DEV_STACK_ROUTER_URL)]
    pub router_url: String,

    #[arg(long)]
    pub team_id: i64,

    /// Person IDs to target (comma-separated). Use `seed` to create targets.
    #[arg(long, value_delimiter = ',', required = true)]
    pub person_ids: Vec<i64>,

    #[arg(long, default_value_t = 5)]
    pub concurrency: usize,

    /// Write-then-read cycles per worker.
    #[arg(long, default_value_t = 100)]
    pub iterations: u64,

    /// Delay between write and read-back.
    #[arg(long, default_value = "0ms", value_parser = humantime::parse_duration)]
    pub read_delay: Duration,
}

#[derive(Args, Clone)]
pub struct GateArgs {
    /// Target an already-running stack at this router URL instead of
    /// spawning one. When unset, the harness spawns its own isolated stack
    /// (replica, leaders, leader-mode router, writer) against the
    /// docker-compose Kafka/etcd/Postgres.
    #[arg(long)]
    pub external_router_url: Option<String>,

    #[arg(long, default_value_t = 900_001)]
    pub team_id: i64,

    /// Number of persons to seed.
    #[arg(long, default_value_t = 100)]
    pub persons: u32,

    /// Number of leader pods to spawn (ignored with --external-router-url).
    #[arg(long, default_value_t = 2)]
    pub leaders: u32,

    /// Number of partitions (ignored with --external-router-url).
    #[arg(long, default_value_t = 4)]
    pub partitions: u32,

    #[arg(long, default_value = "10s", value_parser = humantime::parse_duration)]
    pub duration: Duration,

    #[arg(long, default_value_t = 10)]
    pub concurrency: usize,

    #[arg(long, default_value = DEFAULT_PERSONS_DB_URL)]
    pub persons_db_url: String,

    #[arg(long, default_value = "localhost:9092")]
    pub kafka_hosts: String,

    #[arg(long, default_value = "http://localhost:2379")]
    pub etcd_endpoints: String,

    /// Kill (SIGKILL) the busiest leader this long into the traffic phase.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub kill_after: Option<Duration>,

    /// With --kill-after: also revoke the pod's etcd lease so the
    /// coordinator reacts immediately instead of waiting out the lease TTL.
    #[arg(long, default_value_t = true, action = clap::ArgAction::Set)]
    pub kill_fast: bool,

    /// Gracefully shut down (SIGTERM + drain) the busiest leader this long
    /// into the traffic phase.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub shutdown_after: Option<Duration>,

    /// Spawn an additional leader this long into the traffic phase.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub scale_up_after: Option<Duration>,

    /// Leader cache capacity in entries. Set below --persons to put the
    /// cache under eviction pressure.
    #[arg(long, default_value_t = 100_000)]
    pub cache_capacity: usize,

    /// Leave the spawned stack running after the gate finishes (for
    /// poking at it manually). Ignored with --external-router-url.
    #[arg(long, default_value_t = false)]
    pub keep_stack: bool,

    /// Leave seeded persons in Postgres after the gate finishes.
    #[arg(long, default_value_t = false)]
    pub keep_data: bool,

    /// Directory to build service binaries from / find them in. Defaults to
    /// the directory containing this binary (the cargo target dir).
    #[arg(long)]
    pub bin_dir: Option<std::path::PathBuf>,
}
