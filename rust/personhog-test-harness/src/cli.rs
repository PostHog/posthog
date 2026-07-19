use std::path::PathBuf;
use std::time::Duration;

use clap::{Args, Parser, Subcommand};

pub const DEFAULT_PERSONS_DB_URL: &str =
    "postgres://posthog:posthog@localhost:5432/posthog_persons";

/// The dev-stack leader-mode router (bin/mprocs.yaml `personhog-router-leader`).
pub const DEV_STACK_ROUTER_URL: &str = "http://127.0.0.1:50054";

#[derive(Parser)]
#[command(
    name = "personhog-test-harness",
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
    Gate(Box<GateArgs>),
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
    #[arg(long, default_value = "harness_")]
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

    /// Number of leader-mode routers to spawn. Traffic targets the last
    /// one, which (with 2+ routers) opts out of election candidacy —
    /// coordinator chaos resolves the live election holder and can never
    /// land on the traffic path. Use 3+ so a crash leaves a standby
    /// candidate to win the election.
    #[arg(long, default_value_t = 1)]
    pub routers: u32,

    /// Number of partitions (ignored with --external-router-url).
    #[arg(long, default_value_t = 4)]
    pub partitions: u32,

    #[arg(long, default_value = "10s", value_parser = humantime::parse_duration)]
    pub duration: Duration,

    #[arg(long, default_value_t = 10)]
    pub concurrency: usize,

    /// Read-your-write probers running alongside the blast traffic: each
    /// repeatedly writes a unique key and immediately strong-reads it back,
    /// asserting recency through chaos windows (handoffs, failovers) that
    /// the end-of-run verification cannot see. 0 disables.
    #[arg(long, default_value_t = 2)]
    pub probers: usize,

    #[arg(long, default_value = DEFAULT_PERSONS_DB_URL)]
    pub persons_db_url: String,

    /// The table the writer under test upserts into. Must match the
    /// writer's PG_TARGET_TABLE: spawned stacks run in posthog_person mode;
    /// the dev stack's writer defaults to personhog_person_tmp, so pass
    /// that with --external-router-url against dev.
    #[arg(long, default_value = "posthog_person")]
    pub pg_target_table: String,

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

    /// Crash-restart (SIGKILL + respawn, same pod name) the busiest leader
    /// this long into the traffic phase.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub restart_after: Option<Duration>,

    /// Zombie the busiest leader this long into the traffic phase (SIGSTOP
    /// plus lease revoke), so ownership moves while the process still holds
    /// its old cache and producer.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub zombie_after: Option<Duration>,

    /// How long the zombie stays SIGSTOPped before SIGCONT wakes it.
    #[arg(long, default_value = "8s", value_parser = humantime::parse_duration)]
    pub zombie_duration: Duration,

    /// Crash-restart the writer this long into the traffic phase
    /// (validates at-least-once redelivery under the version guard).
    #[arg(long, value_parser = humantime::parse_duration)]
    pub writer_crash_after: Option<Duration>,

    /// SIGSTOP the writer this long into the traffic phase — controlled
    /// writer-lag injection.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub writer_pause_after: Option<Duration>,

    /// How long the writer stays paused before SIGCONT.
    #[arg(long, default_value = "10s", value_parser = humantime::parse_duration)]
    pub writer_pause_duration: Duration,

    /// SIGKILL the router holding the coordinator election this long
    /// into the traffic phase. Requires --routers >= 3.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub router_kill_after: Option<Duration>,

    /// With --router-kill-after: also revoke the router's registration and
    /// election leases so failover is immediate. Set false for a true
    /// crash — the survivor is blind until both leases expire, exercising
    /// the slow-failover window (election TTL + campaign retry).
    #[arg(long, default_value_t = true, action = clap::ArgAction::Set)]
    pub router_kill_fast: bool,

    /// Gracefully shut down (SIGTERM) the router holding the coordinator
    /// election this long into the traffic phase: the election must hand
    /// over to a survivor immediately via the revoke-on-exit path, not by
    /// waiting out the lease TTL. Requires --routers >= 3.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub router_shutdown_after: Option<Duration>,

    /// After the first handoff-creating event (--shutdown-after or
    /// --scale-up-after) fires, watch for the resulting handoff and SIGKILL
    /// its target pod mid-handoff. Best effort: a handoff that completes
    /// between polls is not killed.
    #[arg(long, default_value_t = false)]
    pub kill_handoff_target: bool,

    /// Leader cache capacity in entries. Set below --persons to put the
    /// cache under eviction pressure.
    #[arg(long, default_value_t = 100_000)]
    pub cache_capacity: usize,

    /// Recovery consumer pool size for spawned leaders
    /// (RECOVERY_POOL_SIZE) — bounds concurrent changelog recoveries.
    #[arg(long, default_value_t = 16)]
    pub recovery_pool_size: usize,

    /// etcd lease TTL for spawned leaders, in seconds. The production
    /// default is 30; lower it (5s works) so a TTL-expiry kill
    /// (--kill-fast false) doesn't need a 30s+ outage window mid-run.
    /// The heartbeat interval scales to a third of this.
    #[arg(long, default_value_t = 30)]
    pub leader_lease_ttl: i64,

    /// Leave the spawned stack running after the gate finishes (for
    /// poking at it manually). Ignored with --external-router-url.
    #[arg(long, default_value_t = false)]
    pub keep_stack: bool,

    /// Leave seeded persons in Postgres after the gate finishes.
    #[arg(long, default_value_t = false)]
    pub keep_data: bool,

    /// Directory containing the service binaries. Defaults to the
    /// workspace target directory for this build profile.
    #[arg(long)]
    pub bin_dir: Option<PathBuf>,
}
