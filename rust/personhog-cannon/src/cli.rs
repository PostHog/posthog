use clap::{Parser, Subcommand};
use std::time::Duration;

#[derive(Parser)]
#[command(
    name = "personhog-cannon",
    about = "Load testing & validation harness for personhog"
)]
pub struct Cli {
    #[arg(long, env = "ROUTER_URL", default_value = "http://localhost:50052", global = true)]
    pub router_url: String,

    #[command(subcommand)]
    pub command: Command,
}

#[derive(Subcommand)]
pub enum Command {
    /// Discover persons in a team for use as test targets
    Discover(DiscoverArgs),
    /// High-throughput property update blast with read-back verification
    Blast(BlastArgs),
    /// Focused write-then-read consistency validation
    Consistency(ConsistencyArgs),
    /// Chaos testing — inspect coordination state, kill/restart leaders, run under disruption
    Chaos(ChaosArgs),
}

#[derive(clap::Args)]
pub struct ChaosArgs {
    #[command(subcommand)]
    pub command: ChaosCommand,
}

#[derive(Subcommand)]
pub enum ChaosCommand {
    /// Show current coordination state (pods, assignments, handoffs)
    Status(ChaosStatusArgs),
    /// Force-delete a leader pod (simulates crash)
    Kill(ChaosKillArgs),
    /// Gracefully delete a leader pod (drain + handoff)
    Shutdown(ChaosShutdownArgs),
    /// Scale the leader StatefulSet up
    ScaleUp(ChaosScaleUpArgs),
    /// Run a blast with scheduled disruptions
    Run(ChaosRunArgs),
}

#[derive(clap::Args)]
pub struct ChaosStatusArgs {
    #[arg(long, env = "ETCD_ENDPOINTS", default_value = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[arg(long, env = "ETCD_PREFIX", default_value = "/personhog/")]
    pub etcd_prefix: String,
}

#[derive(clap::Args)]
pub struct ChaosKillArgs {
    /// Pod name to kill (if not set, picks a running leader pod)
    #[arg(long)]
    pub pod_name: Option<String>,

    /// Also revoke the etcd lease for instant coordinator detection
    #[arg(long)]
    pub fast: bool,

    #[arg(long, env = "NAMESPACE", default_value = "posthog")]
    pub namespace: String,

    #[arg(long, default_value = "app=personhog-leader")]
    pub label: String,

    #[arg(long, env = "ETCD_ENDPOINTS", default_value = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[arg(long, env = "ETCD_PREFIX", default_value = "/personhog/")]
    pub etcd_prefix: String,
}

#[derive(clap::Args)]
pub struct ChaosShutdownArgs {
    /// Pod name to shut down (if not set, picks a running leader pod)
    #[arg(long)]
    pub pod_name: Option<String>,

    #[arg(long, env = "NAMESPACE", default_value = "posthog")]
    pub namespace: String,

    #[arg(long, default_value = "app=personhog-leader")]
    pub label: String,
}

#[derive(clap::Args)]
pub struct ChaosScaleUpArgs {
    /// Target replica count (if not set, increments current by 1)
    #[arg(long)]
    pub replicas: Option<u32>,

    #[arg(long, default_value = "personhog-leader")]
    pub statefulset_name: String,

    #[arg(long, env = "NAMESPACE", default_value = "posthog")]
    pub namespace: String,

    #[arg(long, env = "ETCD_ENDPOINTS", default_value = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[arg(long, env = "ETCD_PREFIX", default_value = "/personhog/")]
    pub etcd_prefix: String,
}

#[derive(clap::Args)]
pub struct ChaosRunArgs {
    #[arg(long)]
    pub team_id: i64,

    /// Person IDs to target (comma-separated)
    #[arg(long, value_delimiter = ',')]
    pub person_ids: Vec<i64>,

    /// Discover persons by these distinct IDs first
    #[arg(long, value_delimiter = ',')]
    pub discover_distinct_ids: Vec<String>,

    /// Number of concurrent workers
    #[arg(long, default_value = "10")]
    pub concurrency: usize,

    /// Total test duration
    #[arg(long, value_parser = humantime::parse_duration)]
    pub duration: Duration,

    // ── Disruption schedule ────────────────────────────────────
    /// Force-delete a leader pod after this duration
    #[arg(long, value_parser = humantime::parse_duration)]
    pub kill_after: Option<Duration>,

    /// Scale the StatefulSet up by 1 after this duration
    #[arg(long, value_parser = humantime::parse_duration)]
    pub scale_up_after: Option<Duration>,

    /// Gracefully delete a leader pod after this duration
    #[arg(long, value_parser = humantime::parse_duration)]
    pub shutdown_after: Option<Duration>,

    /// Pod name to shut down (if not set, picks first found)
    #[arg(long)]
    pub shutdown_pod_name: Option<String>,

    // ── k8s config ─────────────────────────────────────────────
    #[arg(long, env = "NAMESPACE", default_value = "posthog")]
    pub namespace: String,

    #[arg(long, default_value = "personhog-leader")]
    pub statefulset_name: String,

    #[arg(long, default_value = "app=personhog-leader")]
    pub label: String,

    // ── etcd config ────────────────────────────────────────────
    #[arg(long, env = "ETCD_ENDPOINTS", default_value = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[arg(long, env = "ETCD_PREFIX", default_value = "/personhog/")]
    pub etcd_prefix: String,
}

#[derive(clap::Args)]
pub struct DiscoverArgs {
    #[arg(long)]
    pub team_id: i64,

    /// Distinct IDs to look up (comma-separated)
    #[arg(long, value_delimiter = ',')]
    pub distinct_ids: Vec<String>,

    /// Person IDs to look up (comma-separated)
    #[arg(long, value_delimiter = ',')]
    pub person_ids: Vec<i64>,
}

#[derive(clap::Args)]
pub struct BlastArgs {
    #[arg(long)]
    pub team_id: i64,

    /// Person IDs to target (comma-separated)
    #[arg(long, value_delimiter = ',')]
    pub person_ids: Vec<i64>,

    /// Discover persons by these distinct IDs before blasting
    #[arg(long, value_delimiter = ',')]
    pub discover_distinct_ids: Vec<String>,

    /// Number of concurrent workers
    #[arg(long, default_value = "10")]
    pub concurrency: usize,

    /// Test duration (e.g. "30s", "2m")
    #[arg(long, value_parser = humantime::parse_duration)]
    pub duration: Duration,

    /// Property key prefix for generated updates
    #[arg(long, default_value = "cannon_")]
    pub property_prefix: String,

    /// Verify reads after all writes complete
    #[arg(long, default_value = "true")]
    pub verify: bool,
}

#[derive(clap::Args)]
pub struct ConsistencyArgs {
    #[arg(long)]
    pub team_id: i64,

    /// Person IDs to test against (comma-separated)
    #[arg(long, value_delimiter = ',')]
    pub person_ids: Vec<i64>,

    /// Discover persons by these distinct IDs first
    #[arg(long, value_delimiter = ',')]
    pub discover_distinct_ids: Vec<String>,

    /// Number of concurrent workers
    #[arg(long, default_value = "5")]
    pub concurrency: usize,

    /// Number of write-then-read cycles per person
    #[arg(long, default_value = "100")]
    pub iterations: u64,

    /// Delay between write and read-back (e.g. "0ms", "10ms")
    #[arg(long, value_parser = humantime::parse_duration, default_value = "0ms")]
    pub read_delay: Duration,
}
