use std::path::PathBuf;
use std::time::Duration;

use clap::{Args, Parser, Subcommand};

pub const DEFAULT_PERSONS_DB_URL: &str =
    "postgres://posthog:posthog@localhost:5432/posthog_persons";

/// The dev-stack leader-mode router (bin/mprocs.yaml `personhog-router-leader`).
pub const DEV_STACK_ROUTER_URL: &str = "http://127.0.0.1:50054";

/// Connections a load-driving scenario opens to the router by default.
/// Sized so a deployed instance spreads over a meaningful slice of a
/// router fleet while staying trivial against a single local router.
pub const DEFAULT_ROUTER_CHANNELS: usize = 8;

/// Keys a traffic lane holds a person's document at. The changelog carries
/// the whole document per update, so this multiplies the bed's byte rate.
pub const DEFAULT_KEYS_PER_PERSON: u64 = 64;

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
    /// Continuous synthetic traffic with epoch-based verification, for the
    /// dev deployment. A startup sentinel round-trip refuses to send
    /// traffic anywhere the router does not serve the database this harness
    /// seeds, and every database operation is confined to the configured
    /// validation table.
    Traffic(Box<TrafficArgs>),
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

    /// Table to seed into — the same table the stack's writer targets
    /// and its leader's fallback reads.
    #[arg(long, default_value = "personhog_person_tmp")]
    pub pg_target_table: String,
}

#[derive(Args, Clone)]
pub struct CleanupArgs {
    #[arg(long)]
    pub team_id: i64,

    #[arg(long, default_value = DEFAULT_PERSONS_DB_URL)]
    pub persons_db_url: String,

    /// Table to delete the team's rows from.
    #[arg(long, default_value = "personhog_person_tmp")]
    pub pg_target_table: String,
}

#[derive(Args, Clone)]
pub struct BlastArgs {
    #[arg(long, default_value = DEV_STACK_ROUTER_URL)]
    pub router_url: String,

    /// Connections to open to the router; see TrafficArgs::router_channels.
    #[arg(long, default_value_t = DEFAULT_ROUTER_CHANNELS)]
    pub router_channels: usize,

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

    /// Distinct property keys a person's document settles at. Workers
    /// share this budget, so the document holds its size as concurrency
    /// changes.
    #[arg(long, default_value_t = DEFAULT_KEYS_PER_PERSON)]
    pub property_keys_per_person: u64,

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
    /// Extra KEY=VALUE environment for spawned leaders — the lever for
    /// benchmarking leader features (e.g. KAFKA_TRANSACTIONAL_FENCING)
    /// without a harness change per flag. Repeatable.
    #[arg(long = "leader-env", value_parser = parse_env_pair)]
    pub leader_env: Vec<(String, String)>,

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

    /// The table every stack component and harness operation uses:
    /// spawned stacks set it as the writer's PG_TARGET_TABLE and the
    /// leader's FALLBACK_TABLE, and the harness seeds, verifies, and
    /// cleans up in it. posthog_person is deliberately never touched.
    #[arg(long, default_value = "personhog_person_tmp")]
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

    /// Fence the first --fence-count seeded persons (delete-op lifecycle
    /// fence via the router) this long into the traffic phase. While
    /// fenced, any write acked above the sealed version is a violation —
    /// this is what catches a fence failing open across a leader crash or
    /// handoff (compose with --restart-after / --kill-after between fence
    /// and release). Requires --fence-release-after.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub fence_after: Option<Duration>,

    /// Release the fences (aborted outcome — the persons resume life) this
    /// long into the traffic phase. Must be after --fence-after.
    #[arg(long, value_parser = humantime::parse_duration)]
    pub fence_release_after: Option<Duration>,

    /// How many seeded persons the fence window covers.
    #[arg(long, default_value_t = 5)]
    pub fence_count: usize,

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

    /// Leader per-partition cache budget in bytes (CACHE_MEMORY_CAPACITY_BYTES).
    /// Set below the seeded pool's footprint to put the cache under
    /// eviction pressure. Default matches the dev deployment (16 MiB).
    #[arg(long, default_value_t = 16_777_216)]
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

    /// Create the persons through the personhog-identity service
    /// (GetOrCreatePersonsByDistinctIds with initial properties) instead of
    /// seeding SQL directly. The create acks are journaled like any other
    /// write, so the gate also asserts create visibility: the initial
    /// properties must survive into strong reads and Postgres. A spawned
    /// stack brings up its own identity service; with
    /// --external-router-url, pass --external-identity-url too.
    #[arg(long, default_value_t = false)]
    pub create_via_identity: bool,

    /// Identity service URL for --create-via-identity against an
    /// already-running stack (the dev stack runs it at
    /// http://127.0.0.1:50055). Ignored for spawned stacks.
    #[arg(long)]
    pub external_identity_url: Option<String>,

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

#[derive(Args, Clone)]
pub struct TrafficArgs {
    /// Router serving the personhog stack under continuous test.
    #[arg(long, env = "TRAFFIC_ROUTER_URL")]
    pub router_url: String,

    /// Identity service under test: the epoch pool is created through
    /// get-or-create and rotated through the lifecycle delete saga, both
    /// served on this address.
    #[arg(long, env = "TRAFFIC_IDENTITY_URL")]
    pub identity_url: String,

    /// Connections this instance opens to the router. A Kubernetes Service
    /// pins each connection to one router pod, so a single connection
    /// confines an instance's whole load to one pod and measures that
    /// pod's ceiling rather than the fleet's.
    #[arg(long, env = "TRAFFIC_ROUTER_CHANNELS", default_value_t = DEFAULT_ROUTER_CHANNELS)]
    pub router_channels: usize,

    /// Master toggle. When false the process starts fully (guard, metrics,
    /// liveness) but idles instead of driving traffic — so a deployed-but-
    /// disabled harness is observably "off on purpose" rather than absent.
    /// The chart ships false and flips it to start traffic; the CLI
    /// defaults to true because invoking `traffic` means traffic.
    #[arg(long, env = "TRAFFIC_ENABLED", default_value_t = true, action = clap::ArgAction::Set)]
    pub enabled: bool,

    /// Reserved harness teams (comma-separated). The traffic mode owns
    /// every row on them. The drawn blast rate and the probers are
    /// instance totals shared across the teams, so team count tunes
    /// partition spread, not offered load; pool size and concurrency
    /// apply per team.
    #[arg(
        long,
        env = "TRAFFIC_TEAM_IDS",
        value_delimiter = ',',
        default_value = "900101"
    )]
    pub team_ids: Vec<i64>,

    /// Dedicated team for the hostile lane, kept out of the exactness
    /// journal (its outcomes are observed as metrics, not verified).
    #[arg(long, env = "TRAFFIC_HOSTILE_TEAM_ID", default_value_t = 900_102)]
    pub hostile_team_id: i64,

    #[arg(long, env = "TRAFFIC_PERSONS_DB_URL", default_value = DEFAULT_PERSONS_DB_URL)]
    pub persons_db_url: String,

    /// The table the writer under test upserts into (the dev writer's
    /// PG_TARGET_TABLE).
    #[arg(
        long,
        env = "TRAFFIC_PG_TARGET_TABLE",
        default_value = "personhog_person_tmp"
    )]
    pub pg_target_table: String,

    /// Persons seeded per epoch, rotated at epoch close.
    #[arg(long, env = "TRAFFIC_POOL_SIZE", default_value_t = 200)]
    pub pool_size: u32,

    /// Distinct property keys a person's document settles at. Rotation
    /// alone does not bound it: writes per person scale with the drawn
    /// rate, so a high enough rate reaches the admission ceiling inside
    /// one epoch.
    #[arg(
        long,
        env = "TRAFFIC_PROPERTY_KEYS_PER_PERSON",
        default_value_t = DEFAULT_KEYS_PER_PERSON
    )]
    pub property_keys_per_person: u64,

    /// Verification epoch length: traffic runs, then the epoch's acked
    /// writes are verified against strong reads and Postgres, then the
    /// person pool rotates.
    #[arg(long, env = "TRAFFIC_EPOCH", default_value = "5m", value_parser = humantime::parse_duration)]
    pub epoch: Duration,

    /// Each epoch draws its target write rate uniformly from this range
    /// (writes/second), which also exercises the autoscaler.
    #[arg(long, env = "TRAFFIC_RATE_MIN", default_value_t = 50.0)]
    pub rate_min: f64,

    #[arg(long, env = "TRAFFIC_RATE_MAX", default_value_t = 500.0)]
    pub rate_max: f64,

    /// Concurrent write workers sharing the epoch's target rate.
    #[arg(long, env = "TRAFFIC_CONCURRENCY", default_value_t = 20)]
    pub concurrency: usize,

    /// Read-your-write probers running alongside the writers: an
    /// instance total, distributed across the teams and rotated each
    /// epoch (probers are unpaced, so a per-team count would scale
    /// probing load with the team count).
    #[arg(long, env = "TRAFFIC_PROBERS", default_value_t = 2)]
    pub probers: usize,

    /// Hostile-lane writes per second (NUL and oversized payloads against
    /// the hostile team). 0 disables.
    #[arg(long, env = "TRAFFIC_HOSTILE_RATE", default_value_t = 1.0)]
    pub hostile_rate: f64,

    /// Prometheus metrics + liveness port.
    #[arg(long, env = "TRAFFIC_METRICS_PORT", default_value_t = 9110)]
    pub metrics_port: u16,

    /// Continuous chaos: kill scenarios against the stack under test on
    /// a randomized cadence. Ships false; the chart flips it once RBAC
    /// is in place. Requires the harness ServiceAccount to hold pod
    /// get/list/delete in the target namespaces.
    #[arg(long, env = "CHAOS_ENABLED", default_value_t = false, action = clap::ArgAction::Set)]
    pub chaos_enabled: bool,

    /// Bounds of the randomized pause between chaos scenarios.
    #[arg(long, env = "CHAOS_INTERVAL_MIN", default_value = "180s", value_parser = humantime::parse_duration)]
    pub chaos_interval_min: Duration,

    #[arg(long, env = "CHAOS_INTERVAL_MAX", default_value = "600s", value_parser = humantime::parse_duration)]
    pub chaos_interval_max: Duration,

    /// Namespaces of the target classes. Each class's app pods are
    /// selected by `app.kubernetes.io/name=<namespace>` plus
    /// `component=app`, which in the personhog charts matches the
    /// namespace name and excludes pgbouncer sidecars.
    #[arg(
        long,
        env = "CHAOS_LEADER_NAMESPACE",
        default_value = "personhog-leader"
    )]
    pub chaos_leader_namespace: String,

    #[arg(
        long,
        env = "CHAOS_ROUTER_NAMESPACE",
        default_value = "personhog-router-leader"
    )]
    pub chaos_router_namespace: String,

    #[arg(
        long,
        env = "CHAOS_WRITER_NAMESPACE",
        default_value = "personhog-writer"
    )]
    pub chaos_writer_namespace: String,

    /// etcd endpoints of the stack under test (comma-separated). Enables
    /// the coordinator-targeted scenarios, which resolve the live
    /// election holder; absent, those scenarios are excluded.
    #[arg(long, env = "CHAOS_ETCD_ENDPOINTS")]
    pub chaos_etcd_endpoints: Option<String>,

    /// etcd key prefix, matching the routers' ETCD_PREFIX.
    #[arg(long, env = "CHAOS_ETCD_PREFIX", default_value = "/personhog/")]
    pub chaos_etcd_prefix: String,

    /// Namespace of the etcd cluster's own pods. Enables the
    /// `etcd_bounce` scenario (abruptly kill one member of a healthy
    /// three-member cluster); absent, that scenario is excluded. The
    /// harness ServiceAccount additionally needs pod list/delete RBAC in
    /// this namespace.
    #[arg(long, env = "CHAOS_ETCD_NAMESPACE")]
    pub chaos_etcd_namespace: Option<String>,
}

/// Environment the stack assigns per leader; overriding any of these
/// would break pod identity or point a spawned leader at the wrong
/// topic or table, and the resulting run would look like a real result.
const RESERVED_LEADER_ENV: &[&str] = &[
    "POD_NAME",
    "GRPC_ADDRESS",
    "METRICS_PORT",
    "ETCD_ENDPOINTS",
    "ETCD_PREFIX",
    "KAFKA_PERSON_STATE_TOPIC",
    "FALLBACK_TABLE",
    "FALLBACK_DATABASE_URL",
    "WRITER_CONSUMER_GROUP",
    // Derived fencing timeouts scale off the lease TTL, so overriding it
    // here would silently contradict --leader-lease-ttl and can leave a
    // fenced leader unable to start.
    "LEASE_TTL",
];

/// Parse a `KEY=VALUE` pair for environment passthrough arguments.
fn parse_env_pair(s: &str) -> Result<(String, String), String> {
    let (key, value) = s
        .split_once('=')
        .ok_or_else(|| format!("expected KEY=VALUE, got {s:?}"))?;
    if key.is_empty() {
        return Err(format!("empty environment variable name in {s:?}"));
    }
    if RESERVED_LEADER_ENV.contains(&key) {
        return Err(format!(
            "{key} is assigned per leader by the harness and cannot be overridden"
        ));
    }
    Ok((key.to_string(), value.to_string()))
}
