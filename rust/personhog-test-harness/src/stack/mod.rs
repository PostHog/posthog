use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{bail, ensure, Context, Result};
use personhog_coordination::follow::REBIND_LOG;
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::{
    ChangelogTarget, ClusterEndpoint, HandoffPhase, MigrationPhase, MigrationRequest,
};

mod etcd;
pub(crate) mod kafka;
mod process;

use process::ServiceProcess;

use crate::cli::PropertyStorage;

/// Ports sit in their own range so a harness stack can run alongside the
/// dev stack (gRPC 50051-50054, metrics 9100-9105) without collisions.
/// Routers occupy base..base+3 and leaders start at base+6, which caps the
/// router count at 4.
///
/// The range must stay below 32768: Linux allocates the local port of
/// every outbound connection from the ephemeral range (default
/// 32768-60999), so a fixed listen port inside it loses a lottery against
/// whichever process's Kafka/PG/etcd connection grabbed the port first —
/// during bring-up, every service opens outbound sockets in the same
/// instant the listeners bind.
const REPLICA_GRPC_PORT: u16 = 24051;
const IDENTITY_GRPC_PORT: u16 = 24052;
const ROUTER_GRPC_BASE_PORT: u16 = 24054;
const LEADER_GRPC_BASE_PORT: u16 = 24060;
const REPLICA_METRICS_PORT: u16 = 24151;
const IDENTITY_METRICS_PORT: u16 = 24152;
const WRITER_METRICS_PORT: u16 = 24153;
const ROUTER_METRICS_BASE_PORT: u16 = 24154;
const WRITER_CONSUMER_GROUP: &str = "personhog-test-harness-writer";
const LEADER_METRICS_BASE_PORT: u16 = 24160;
/// Above the leader range, which grows with every scale-up.
const PUBLISHER_METRICS_BASE_PORT: u16 = 24200;
const EXTRA_WRITER_METRICS_BASE_PORT: u16 = 24250;
/// Above the publishers, whose count is a flag.
const MONITOR_PORT: u16 = 24300;
/// Short, because a fixture's run ends with a wait for the last entries to
/// settle; long enough to cover the publisher drain on a loaded CI runner.
const MONITOR_GRACE_SECONDS: u64 = 15;
const MONITOR_IDLE_PARTITION_SECONDS: u64 = 3;
const MAX_ROUTERS: u32 = 4;
/// Partitions of the two per-run publish topics. More than one, so the
/// keyed merge events spread the way they do in production.
const PUBLISH_TOPIC_PARTITIONS: u32 = 4;

const ETCD_PREFIX: &str = "/personhog-test-harness/";
const READY_DEADLINE: Duration = Duration::from_secs(90);
const MIGRATION_DEADLINE: Duration = Duration::from_secs(180);
const MIGRATION_POLL: Duration = Duration::from_millis(100);
const RETIREMENT_DEADLINE: Duration = Duration::from_secs(60);
const WRITER_MOVE_DEADLINE: Duration = Duration::from_secs(10);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

pub struct StackConfig {
    /// Directory containing the service binaries (the cargo target dir).
    pub bin_dir: PathBuf,
    pub leaders: u32,
    pub writers: u32,
    pub property_storage: PropertyStorage,
    pub routers: u32,
    pub partitions: u32,
    pub kafka_hosts: String,
    pub secondary_kafka_hosts: Option<String>,
    pub etcd_endpoints: String,
    pub persons_db_url: String,
    /// Writer flush cadence. Short by default so gate quiesce is quick.
    pub writer_flush_interval_ms: u64,
    /// The table the writer upserts into.
    pub pg_target_table: String,
    /// Leader per-partition cache budget in bytes (entries are weighed
    /// by serialized size). Lower it below the seeded pool's footprint
    /// to put the cache under eviction pressure.
    pub cache_memory_capacity: usize,
    /// Extra environment for spawned leaders, appended after the
    /// standard set (so it can override any of it).
    pub extra_leader_env: Vec<(String, String)>,
    pub extra_router_env: Vec<(String, String)>,
    pub recovery_pool_size: usize,
    /// etcd lease TTL for leaders, in seconds. Bounds how long a crashed
    /// (unrevoked) leader stays the registered owner.
    pub leader_lease_ttl: i64,
    /// Also spawn the personhog-identity service, pointed at the traffic
    /// router for its initial-properties writes. Only needed when the run
    /// creates persons through the identity path.
    pub spawn_identity: bool,
    /// Also spawn `personhog-publisher` replicas that drain the outbox the
    /// identity service writes, to two per-run topics. Needs
    /// `spawn_identity`: nothing else writes the outbox.
    pub publish: Option<PublishConfig>,
    /// Also spawn the parity monitor against the publish topics; needs `publish`.
    pub monitor: Option<MonitorConfig>,
}

pub struct PublishConfig {
    pub publishers: u32,
    pub rows_per_pass: i64,
}

pub struct MonitorConfig {
    pub node_distinct_ids_topic: String,
    pub node_merge_events_topic: String,
}

#[derive(Clone)]
pub struct PublishTopics {
    pub distinct_ids: String,
    pub merge_events: String,
}

/// A locally-spawned personhog stack: replica, writer, N leaders, and M
/// leader-mode routers (each hosting a coordinator candidate), all pointed
/// at the docker-compose Kafka/etcd/Postgres but isolated from the dev
/// stack via their own ports, etcd prefix, and per-run changelog topic.
/// Identity's companion tables; its env must name the full set.
struct IdentityCompanionTables {
    person_distinct_id: &'static str,
    ff_hash_key_override: &'static str,
    lifecycle_op: &'static str,
    lifecycle_op_person: &'static str,
    person_publish_outbox: &'static str,
}

pub struct Stack {
    config: StackConfig,
    infra: Vec<ServiceProcess>,
    /// Live routers, keyed by registration name. The first spawned almost
    /// always wins the coordinator election, so traffic targets the LAST
    /// router and chaos kills the first.
    routers: Vec<(String, ServiceProcess)>,
    /// Live leaders, keyed by the pod name they registered with.
    leaders: Vec<(String, ServiceProcess)>,
    /// A SIGSTOPped zombie leader, waiting for its SIGCONT.
    paused: Vec<(String, ServiceProcess)>,
    /// Processes removed by chaos (killed, draining, or resumed zombies);
    /// their exit is expected, so they are excluded from liveness checks.
    retired: Vec<ServiceProcess>,
    next_leader_index: u32,
    store: PersonhogStore,
    topic: String,
    /// Topics a migration moved off; deleted with the live one at teardown.
    retired_topics: Vec<String>,
    secondary_topics: HashSet<String>,
    writer_rebinds: usize,
    /// Old generations awaiting the writer's drain and the retire op, with the saga's end.
    pending_retire: Vec<(String, Instant)>,
    slatedb_from: Option<u32>,
    replaced_leader_metrics: Vec<(String, bool, String)>,
    pub router_url: String,
    /// Set when the stack spawned a personhog-identity service: the traffic
    /// router's URL, which proxies identity RPCs to it.
    pub identity_url: Option<String>,
    publish_topics: Option<PublishTopics>,
    pub monitor_url: Option<String>,
    pub log_dir: PathBuf,
}

impl Stack {
    /// The distinct id and hash-key-override tables paired with a person
    /// table. Identity writes the mapping (and clears overrides) in the same
    /// id namespace as its person table, so the three always travel together.
    fn identity_companion_tables(person_table: &str) -> Result<IdentityCompanionTables> {
        let (lifecycle_op, lifecycle_op_person) = crate::seed::lifecycle_tables_for(person_table);
        let person_publish_outbox = crate::seed::publish_outbox_table_for(person_table);
        match person_table {
            "posthog_person" => Ok(IdentityCompanionTables {
                person_distinct_id: "posthog_persondistinctid",
                ff_hash_key_override: "posthog_featureflaghashkeyoverride",
                lifecycle_op,
                lifecycle_op_person,
                person_publish_outbox,
            }),
            "personhog_person_tmp" => Ok(IdentityCompanionTables {
                person_distinct_id: "personhog_persondistinctid_tmp",
                ff_hash_key_override: "personhog_featureflaghashkeyoverride_tmp",
                lifecycle_op,
                lifecycle_op_person,
                person_publish_outbox,
            }),
            other => bail!(
                "--create-via-identity has no known identity table set for \
                 --pg-target-table {other:?}"
            ),
        }
    }

    pub async fn up(mut config: StackConfig) -> Result<Self> {
        if config.property_storage == PropertyStorage::Slatedb {
            config
                .extra_leader_env
                .push(("PROPERTY_SOURCE".to_string(), "slatedb".to_string()));
        }
        if config.routers == 0 || config.routers > MAX_ROUTERS {
            bail!("--routers must be between 1 and {MAX_ROUTERS}");
        }
        if config.publish.is_some() && !config.spawn_identity {
            bail!("publishing needs the identity service: nothing else writes the outbox");
        }
        if config.monitor.is_some() && config.publish.is_none() {
            bail!("the parity monitor needs the publish topics: pass --publish");
        }

        let run_id = chrono::Utc::now().format("%Y%m%d_%H%M%S").to_string();
        let topic = format!("personhog_test_harness_{run_id}");
        let log_dir = config.bin_dir.join("harness-logs").join(&run_id);
        fs::create_dir_all(&log_dir)
            .with_context(|| format!("creating log dir {}", log_dir.display()))?;

        let mut binaries = vec![
            "personhog-replica",
            "personhog-router",
            "personhog-leader",
            "personhog-writer",
        ];
        if config.spawn_identity {
            binaries.push("personhog-identity");
        }
        if config.publish.is_some() {
            binaries.push("personhog-publisher");
        }
        if config.monitor.is_some() {
            binaries.push("personhog-parity-monitor");
        }
        for bin in &binaries {
            let path = config.bin_dir.join(bin);
            if !path.exists() {
                bail!(
                    "{} not found — build the stack first:\n  cargo build -p personhog-replica \
                     -p personhog-router -p personhog-leader -p personhog-writer -p personhog-identity{}",
                    path.display(),
                    if config.monitor.is_some() {
                        " -p personhog-parity-monitor"
                    } else {
                        ""
                    }
                );
            }
        }

        tracing::info!(
            leaders = config.leaders,
            routers = config.routers,
            partitions = config.partitions,
            topic,
            log_dir = %log_dir.display(),
            "bringing up stack"
        );

        let store = etcd::connect(&config.etcd_endpoints, ETCD_PREFIX).await?;
        etcd::reset(&store, &topic, config.partitions, WRITER_CONSUMER_GROUP).await?;
        let publish_topics = config.publish.as_ref().map(|_| PublishTopics {
            distinct_ids: format!("{topic}_distinct_ids"),
            merge_events: format!("{topic}_merge_events"),
        });
        let mut topics = vec![(topic.as_str(), config.partitions)];
        if let Some(publish) = &publish_topics {
            topics.push((publish.distinct_ids.as_str(), PUBLISH_TOPIC_PARTITIONS));
            topics.push((publish.merge_events.as_str(), PUBLISH_TOPIC_PARTITIONS));
        }
        kafka::create_topics(&config.kafka_hosts, &topics).await?;

        let mut infra = Vec::new();

        for i in 0..config.writers.max(1) {
            let (name, metrics_port) = match i {
                0 => ("writer".to_string(), WRITER_METRICS_PORT),
                _ => (
                    format!("writer-{i}"),
                    EXTRA_WRITER_METRICS_BASE_PORT + i as u16,
                ),
            };
            infra.push(ServiceProcess::spawn(
                &name,
                &config.bin_dir.join("personhog-writer"),
                &[
                    ("DATABASE_URL", config.persons_db_url.clone()),
                    ("KAFKA_HOSTS", config.kafka_hosts.clone()),
                    ("ETCD_ENDPOINTS", config.etcd_endpoints.clone()),
                    ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
                    ("KAFKA_CONSUMER_GROUP", WRITER_CONSUMER_GROUP.to_string()),
                    (
                        "PROPERTY_STORAGE_MODE",
                        config.property_storage.as_env().to_string(),
                    ),
                    ("PG_TARGET_TABLE", config.pg_target_table.clone()),
                    (
                        "FLUSH_INTERVAL_MS",
                        config.writer_flush_interval_ms.to_string(),
                    ),
                    ("METRICS_PORT", metrics_port.to_string()),
                ],
                &log_dir,
            )?);
        }

        // The replica checks the store layout a writer registers, so in slatedb mode it starts
        // once one has.
        let mut replica_env = vec![
            ("GRPC_ADDRESS", format!("127.0.0.1:{REPLICA_GRPC_PORT}")),
            ("PRIMARY_DATABASE_URL", config.persons_db_url.clone()),
            ("METRICS_PORT", REPLICA_METRICS_PORT.to_string()),
            ("ETCD_ENDPOINTS", config.etcd_endpoints.clone()),
            ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
        ];
        if config.property_storage == PropertyStorage::Slatedb {
            replica_env.push(("PROPERTY_SOURCE", "slatedb".to_string()));
            let mut polls = 0;
            while store.get_property_store_layout().await?.is_none() {
                polls += 1;
                if polls > 150 {
                    bail!("no writer registered the property store layout within 30s");
                }
                tokio::time::sleep(Duration::from_millis(200)).await;
            }
        }
        infra.push(ServiceProcess::spawn(
            "replica",
            &config.bin_dir.join("personhog-replica"),
            &replica_env,
            &log_dir,
        )?);
        // The first router must win the coordinator election so bring-up
        // is deterministic: spawn it alone, wait for it to acquire
        // leadership, then bring up the rest. With two or more routers,
        // traffic targets the LAST one and that router opts out of
        // election candidacy entirely — so no matter how leadership
        // migrates later, coordinator chaos can never be forced to choose
        // between killing the traffic path and killing a standby.
        let mut routers = Vec::new();
        for i in 0..config.routers {
            if i == 1 {
                etcd::wait_for_leader(&store, "harness-router-0", Duration::from_secs(15)).await?;
            }
            let name = format!("harness-router-{i}");
            let is_traffic_router = config.routers >= 2 && i == config.routers - 1;
            let proc = ServiceProcess::spawn_with_extra(
                &name,
                &config.bin_dir.join("personhog-router"),
                &[
                    ("ROUTER_MODE", "leader".to_string()),
                    (
                        "GRPC_ADDRESS",
                        format!("127.0.0.1:{}", ROUTER_GRPC_BASE_PORT + i as u16),
                    ),
                    (
                        "REPLICA_URL",
                        format!("http://127.0.0.1:{REPLICA_GRPC_PORT}"),
                    ),
                    ("ETCD_ENDPOINTS", config.etcd_endpoints.clone()),
                    ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
                    ("BACKEND_TIMEOUT_MS", "5000".to_string()),
                    // Identity RPCs enter through the router, as deployed.
                    ("IDENTITY_ENABLED", config.spawn_identity.to_string()),
                    (
                        "IDENTITY_URL",
                        format!("http://127.0.0.1:{IDENTITY_GRPC_PORT}"),
                    ),
                    ("POD_NAME", name.clone()),
                    ("COORDINATOR_ENABLED", (!is_traffic_router).to_string()),
                    (
                        "METRICS_PORT",
                        (ROUTER_METRICS_BASE_PORT + i as u16).to_string(),
                    ),
                ],
                &config.extra_router_env,
                &log_dir,
            )?;
            routers.push((name, proc));
        }

        let traffic_router_port = ROUTER_GRPC_BASE_PORT + (config.routers - 1) as u16;
        let router_url = format!("http://127.0.0.1:{traffic_router_port}");

        // Identity resolves and creates on the Postgres primary and pushes
        // initial properties through the traffic router; from etcd it reads
        // only the partition count the reset above wrote. Its table set is
        // derived from the stack's person table so identity, writer, and the
        // leader fallback agree on one id namespace.
        let identity_url = if config.spawn_identity {
            let companions = Self::identity_companion_tables(&config.pg_target_table)?;
            infra.push(ServiceProcess::spawn(
                "identity",
                &config.bin_dir.join("personhog-identity"),
                &[
                    ("GRPC_ADDRESS", format!("127.0.0.1:{IDENTITY_GRPC_PORT}")),
                    ("PRIMARY_DATABASE_URL", config.persons_db_url.clone()),
                    ("ROUTER_URL", router_url.clone()),
                    ("ETCD_ENDPOINTS", config.etcd_endpoints.clone()),
                    ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
                    ("METRICS_PORT", IDENTITY_METRICS_PORT.to_string()),
                    ("PERSON_TABLE", config.pg_target_table.clone()),
                    (
                        "PERSON_DISTINCT_ID_TABLE",
                        companions.person_distinct_id.to_string(),
                    ),
                    (
                        "FF_HASH_KEY_OVERRIDE_TABLE",
                        companions.ff_hash_key_override.to_string(),
                    ),
                    ("LIFECYCLE_OP_TABLE", companions.lifecycle_op.to_string()),
                    (
                        "LIFECYCLE_OP_PERSON_TABLE",
                        companions.lifecycle_op_person.to_string(),
                    ),
                    (
                        "PERSON_PUBLISH_OUTBOX_TABLE",
                        companions.person_publish_outbox.to_string(),
                    ),
                    // The service default is off. The gate needs the
                    // sweeper: a leader kill abandons a merge mid-saga,
                    // and only the sweeper re-drives it. The short
                    // interval fits a short run.
                    ("LIFECYCLE_SWEEPER_ENABLED", "true".to_string()),
                    ("LIFECYCLE_SWEEP_INTERVAL_SECS", "3".to_string()),
                    (
                        "LIFECYCLE_OUTBOX_ENABLED",
                        config.publish.is_some().to_string(),
                    ),
                ],
                &log_dir,
            )?);
            if let (Some(publish), Some(topics)) = (&config.publish, &publish_topics) {
                for i in 0..publish.publishers {
                    infra.push(ServiceProcess::spawn(
                        &format!("publisher-{i}"),
                        &config.bin_dir.join("personhog-publisher"),
                        &[
                            ("PRIMARY_DATABASE_URL", config.persons_db_url.clone()),
                            ("PERSON_TABLE", config.pg_target_table.clone()),
                            (
                                "PERSON_DISTINCT_ID_TABLE",
                                companions.person_distinct_id.to_string(),
                            ),
                            (
                                "FF_HASH_KEY_OVERRIDE_TABLE",
                                companions.ff_hash_key_override.to_string(),
                            ),
                            ("LIFECYCLE_OP_TABLE", companions.lifecycle_op.to_string()),
                            (
                                "LIFECYCLE_OP_PERSON_TABLE",
                                companions.lifecycle_op_person.to_string(),
                            ),
                            (
                                "PERSON_PUBLISH_OUTBOX_TABLE",
                                companions.person_publish_outbox.to_string(),
                            ),
                            ("KAFKA_HOSTS", config.kafka_hosts.clone()),
                            ("PERSON_DISTINCT_ID_TOPIC", topics.distinct_ids.clone()),
                            ("PERSON_MERGE_EVENTS_ENABLED", "true".to_string()),
                            ("PERSON_MERGE_EVENTS_TOPIC", topics.merge_events.clone()),
                            ("PERSON_MERGE_EVENTS_TEAM_ALLOWLIST", "*".to_string()),
                            (
                                "LIFECYCLE_PUBLISH_MAX_ROWS_PER_PASS",
                                publish.rows_per_pass.to_string(),
                            ),
                            // A short idle poll, so the drain after traffic
                            // is bounded by the row budget, not the poll.
                            ("LIFECYCLE_PUBLISH_INTERVAL_MS", "50".to_string()),
                            (
                                "METRICS_PORT",
                                (PUBLISHER_METRICS_BASE_PORT + i as u16).to_string(),
                            ),
                        ],
                        &log_dir,
                    )?);
                }
            }
            Some(router_url.clone())
        } else {
            None
        };

        let monitor_url = match (&config.monitor, &publish_topics) {
            (Some(monitor), Some(topics)) => {
                infra.push(ServiceProcess::spawn(
                    "parity-monitor",
                    &config.bin_dir.join("personhog-parity-monitor"),
                    &[
                        ("NODE_KAFKA_HOSTS", config.kafka_hosts.clone()),
                        (
                            "NODE_DISTINCT_ID_TOPIC",
                            monitor.node_distinct_ids_topic.clone(),
                        ),
                        (
                            "NODE_MERGE_EVENTS_TOPIC",
                            monitor.node_merge_events_topic.clone(),
                        ),
                        ("PERSONHOG_KAFKA_HOSTS", config.kafka_hosts.clone()),
                        ("PERSONHOG_DISTINCT_ID_TOPIC", topics.distinct_ids.clone()),
                        ("PERSONHOG_MERGE_EVENTS_TOPIC", topics.merge_events.clone()),
                        ("PARITY_GRACE_SECONDS", MONITOR_GRACE_SECONDS.to_string()),
                        (
                            "PARITY_IDLE_PARTITION_SECONDS",
                            MONITOR_IDLE_PARTITION_SECONDS.to_string(),
                        ),
                        // The readers assign before the ready line, so no
                        // counterpart predates them and every entry is judged.
                        ("PARITY_WARMUP_SECONDS", "0".to_string()),
                        ("PARITY_SWEEP_INTERVAL_MS", "500".to_string()),
                        ("BIND_HOST", "127.0.0.1".to_string()),
                        ("BIND_PORT", MONITOR_PORT.to_string()),
                    ],
                    &log_dir,
                )?);
                Some(format!("http://127.0.0.1:{MONITOR_PORT}"))
            }
            _ => None,
        };

        let slatedb_from = (config.property_storage == PropertyStorage::Slatedb).then_some(0);
        let mut stack = Self {
            config,
            infra,
            routers,
            leaders: Vec::new(),
            paused: Vec::new(),
            retired: Vec::new(),
            next_leader_index: 0,
            store,
            topic,
            retired_topics: Vec::new(),
            secondary_topics: HashSet::new(),
            writer_rebinds: 0,
            pending_retire: Vec::new(),
            slatedb_from,
            replaced_leader_metrics: Vec::new(),
            router_url,
            identity_url,
            publish_topics,
            monitor_url,
            log_dir,
        };

        for _ in 0..stack.config.leaders {
            stack.spawn_leader()?;
        }

        let (partitions, leaders) = (stack.config.partitions, stack.config.leaders);
        stack
            .wait_ready(partitions, leaders)
            .await
            .inspect_err(|_| stack.dump_recent_logs())?;

        Ok(stack)
    }

    /// Spawn one more leader. The pod derives its advertise address from
    /// its concrete bind and registers it for the router to dial.
    pub fn spawn_leader(&mut self) -> Result<String> {
        let index = self.next_leader_index;
        self.next_leader_index += 1;
        let (lifecycle_op, lifecycle_op_person) =
            crate::seed::lifecycle_tables_for(&self.config.pg_target_table);

        let grpc_port = LEADER_GRPC_BASE_PORT + index as u16;
        // A real pod name: the leader derives its advertise address from
        // its concrete bind, registers it, and the router dials what the
        // routing table carries — the same path a deployment takes.
        let pod_name = format!("personhog-leader-{index}");
        let grpc_address = format!("127.0.0.1:{grpc_port}");
        // Heartbeats must land well inside the lease window or a healthy
        // pod's lease expires between renewals.
        let heartbeat_secs = (self.config.leader_lease_ttl / 3).max(1);
        let proc = ServiceProcess::spawn_with_extra(
            &format!("leader-{index}"),
            &self.config.bin_dir.join("personhog-leader"),
            &[
                ("GRPC_ADDRESS", grpc_address),
                ("POD_NAME", pod_name.clone()),
                ("LEASE_TTL", self.config.leader_lease_ttl.to_string()),
                ("HEARTBEAT_INTERVAL_SECS", heartbeat_secs.to_string()),
                (
                    "CACHE_MEMORY_CAPACITY_BYTES",
                    self.config.cache_memory_capacity.to_string(),
                ),
                (
                    "RECOVERY_POOL_SIZE",
                    self.config.recovery_pool_size.to_string(),
                ),
                ("ETCD_ENDPOINTS", self.config.etcd_endpoints.clone()),
                ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
                ("KAFKA_HOSTS", self.config.kafka_hosts.clone()),
                // Must match the spawned writer's consumer group or the
                // leader's committed-offset queries (warming ranges, dirty
                // index pruning) silently see no progress at all.
                ("WRITER_CONSUMER_GROUP", WRITER_CONSUMER_GROUP.to_string()),
                ("FALLBACK_DATABASE_URL", self.config.persons_db_url.clone()),
                // Pair the fallback with the spawned writer's target: the
                // dirty index treats an unmarked person's PG row as
                // current, which is only true of the writer's own table.
                ("FALLBACK_TABLE", self.config.pg_target_table.clone()),
                ("LIFECYCLE_OP_TABLE", lifecycle_op.to_string()),
                ("LIFECYCLE_OP_PERSON_TABLE", lifecycle_op_person.to_string()),
                (
                    "METRICS_PORT",
                    (LEADER_METRICS_BASE_PORT + index as u16).to_string(),
                ),
            ],
            &self.config.extra_leader_env,
            &self.log_dir,
        )?;

        self.leaders.push((pod_name.clone(), proc));
        Ok(pod_name)
    }

    /// SIGKILL the leader owning the most partitions (a crash, maximum
    /// blast radius). With `fast`, also revoke its etcd lease so the
    /// coordinator reacts immediately instead of waiting out the lease TTL.
    pub async fn kill_leader(&mut self, fast: bool) -> Result<String> {
        let victim = self.busiest_leader().await?;
        let (pod_name, mut proc) = self.remove_leader(&victim)?;

        proc.kill_now().await;
        tracing::info!(pod = %pod_name, fast, "killed leader");
        if fast {
            etcd::revoke_pod_lease(&self.store, &pod_name).await?;
        }
        self.retired.push(proc);
        Ok(pod_name)
    }

    /// SIGTERM the busiest leader and let it drain: it transitions to
    /// Draining, the coordinator hands its partitions off, and the process
    /// exits on its own while traffic continues.
    pub async fn shutdown_leader(&mut self) -> Result<String> {
        let victim = self.busiest_leader().await?;
        self.shutdown_named_leader(&victim)
    }

    fn shutdown_named_leader(&mut self, victim: &str) -> Result<String> {
        let (pod_name, proc) = self.remove_leader(victim)?;

        proc.sigterm();
        tracing::info!(pod = %pod_name, "requested graceful shutdown");
        self.retired.push(proc);
        Ok(pod_name)
    }

    pub async fn roll_leaders_to_slatedb(&mut self, step_deadline: Duration) -> Result<()> {
        self.config
            .extra_leader_env
            .push(("PROPERTY_SOURCE".to_string(), "slatedb".to_string()));
        self.slatedb_from = Some(self.next_leader_index);
        let old: Vec<String> = self.leaders.iter().map(|(name, _)| name.clone()).collect();
        for victim in old {
            let surged = self.spawn_leader()?;
            let started = Instant::now();
            while !self
                .store
                .list_assignments()
                .await?
                .iter()
                .any(|a| a.owner == surged)
            {
                ensure!(
                    started.elapsed() < step_deadline,
                    "{surged} took no partition within {step_deadline:?}"
                );
                self.check_alive()?;
                tokio::time::sleep(MIGRATION_POLL).await;
            }
            self.wait_converged(step_deadline).await?;
            let page = self.scrape_leader(&victim).await?;
            self.replaced_leader_metrics.push(page);
            self.shutdown_named_leader(&victim)?;
            self.wait_converged(step_deadline).await?;
            println!("Rollout: {victim} replaced by SlateDB leader {surged}");
        }
        Ok(())
    }

    pub async fn leader_metrics(&self) -> Result<Vec<(String, bool, String)>> {
        let mut pages = self.replaced_leader_metrics.clone();
        for (name, _) in &self.leaders {
            pages.push(self.scrape_leader(name).await?);
        }
        Ok(pages)
    }

    async fn scrape_leader(&self, name: &str) -> Result<(String, bool, String)> {
        let index: u32 = name
            .rsplit('-')
            .next()
            .and_then(|i| i.parse().ok())
            .with_context(|| format!("leader name {name} carries no index"))?;
        let url = format!(
            "http://127.0.0.1:{}/metrics",
            LEADER_METRICS_BASE_PORT + index as u16
        );
        let page = reqwest::get(&url)
            .await
            .and_then(reqwest::Response::error_for_status)
            .with_context(|| format!("scraping {name}"))?
            .text()
            .await?;
        let slatedb = self.slatedb_from.is_some_and(|from| index >= from);
        Ok((name.to_string(), slatedb, page))
    }

    /// Crash-restart the busiest leader under the same identity: SIGKILL,
    /// then immediately respawn with the same pod name and ports, the way a
    /// StatefulSet brings a crashed pod back. The restarted process
    /// re-registers and must converge on the partitions etcd still says it
    /// owns.
    pub async fn restart_leader(&mut self) -> Result<String> {
        let victim = self.busiest_leader().await?;
        let position = self
            .leaders
            .iter()
            .position(|(name, _)| *name == victim)
            .context("victim leader not tracked")?;

        self.leaders[position].1.respawn().await?;
        tracing::info!(pod = %victim, "crash-restarted leader");
        Ok(victim)
    }

    /// Turn the busiest leader into a zombie: SIGSTOP it (unreachable but
    /// not dead) and revoke its lease so ownership moves while the process
    /// still holds its old cache and producer. `resume_zombie` wakes it.
    pub async fn stop_zombie(&mut self) -> Result<String> {
        let victim = self.busiest_leader().await?;
        let (pod_name, proc) = self.remove_leader(&victim)?;

        proc.sigstop();
        tracing::info!(pod = %pod_name, "SIGSTOPped leader (zombie)");
        etcd::revoke_pod_lease(&self.store, &pod_name).await?;
        self.paused.push((pod_name.clone(), proc));
        Ok(pod_name)
    }

    /// SIGSTOP the busiest leader with its lease intact: registered and
    /// owning, but unable to drain, ack or serve until `resume_stalled`.
    pub async fn stall_leader(&mut self) -> Result<String> {
        let victim = self.busiest_leader().await?;
        self.stall_named(&victim)
    }

    fn stall_named(&mut self, victim: &str) -> Result<String> {
        let (pod_name, proc) = self.remove_leader(victim)?;
        proc.sigstop();
        tracing::info!(pod = %pod_name, "SIGSTOPped leader (stalled, lease kept)");
        self.paused.push((pod_name.clone(), proc));
        Ok(pod_name)
    }

    /// SIGKILL the stalled leader and revoke its lease.
    async fn kill_stalled(&mut self) -> Result<String> {
        let (pod_name, mut proc) = self.paused.pop().context("no stalled leader to kill")?;
        proc.kill_now().await;
        etcd::revoke_pod_lease(&self.store, &pod_name).await?;
        tracing::info!(pod = %pod_name, "killed stalled leader");
        self.retired.push(proc);
        Ok(pod_name)
    }

    /// Whether every partition the saga holds on `pod` carries its drained ack.
    async fn holder_drained(&self, pod: &str) -> Result<bool> {
        for held in self.store.list_handoffs().await? {
            if held.held_by.is_none() || held.new_owner != pod {
                continue;
            }
            let acks = self.store.list_drained_acks(held.partition).await?;
            if !acks
                .iter()
                .any(|a| a.pod_name == pod && a.handoff_id == held.handoff_id)
            {
                return Ok(false);
            }
        }
        Ok(true)
    }

    /// SIGCONT the stalled leader; it resumes exactly where it was.
    pub fn resume_stalled(&mut self) -> Result<String> {
        let (pod_name, proc) = self.paused.pop().context("no stalled leader to resume")?;
        proc.sigcont();
        tracing::info!(pod = %pod_name, "SIGCONTed stalled leader");
        self.leaders.push((pod_name.clone(), proc));
        Ok(pod_name)
    }

    /// SIGCONT the paused zombie. It wakes believing it still owns its
    /// partitions; the contract is that it detects the revoked lease,
    /// self-fences locally, and rejoins with a fresh session — at which
    /// point the rebalancer may legitimately assign it partitions again.
    /// It therefore returns to the live set: convergence counts it as a
    /// valid owner, verification reads data it serves, and check_alive
    /// fails the run if the self-fence path crashes it instead.
    pub fn resume_zombie(&mut self) -> Result<String> {
        let (pod_name, proc) = self
            .paused
            .pop()
            .context("no paused zombie leader to resume")?;
        proc.sigcont();
        tracing::info!(pod = %pod_name, "SIGCONTed zombie leader");
        self.leaders.push((pod_name.clone(), proc));
        Ok(pod_name)
    }

    /// Index of the router currently holding the coordinator election,
    /// resolved live from etcd so chaos targets the actual coordinator
    /// even if leadership migrated after bring-up. Never guesses: lookup
    /// errors propagate (steering a kill off a failed read could target a
    /// standby and pass the gate vacuously), and a vacant election is
    /// polled until a winner emerges — with the 1s campaign retry, well
    /// inside the deadline. Bails if the holder is the traffic router:
    /// candidacy is disabled there, so this can only mean the opt-out
    /// broke — a loud failure here is the regression signal for that
    /// wiring.
    async fn coordinator_router_index(&self) -> Result<usize> {
        let traffic_router = format!("harness-router-{}", self.config.routers - 1);
        let deadline = Instant::now() + Duration::from_secs(5);
        let holder = loop {
            if let Some(leader) = self.store.get_leader().await? {
                break leader.holder;
            }
            if Instant::now() >= deadline {
                bail!("no coordinator elected within 5s; cannot target coordinator chaos");
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        };
        if holder == traffic_router {
            bail!(
                "election held by the traffic router {traffic_router}, which must never \
                 campaign (COORDINATOR_ENABLED=false) — candidacy opt-out is broken"
            );
        }
        self.routers
            .iter()
            .position(|(name, _)| *name == holder)
            .with_context(|| format!("election holder {holder} is not a live router"))
    }

    /// SIGKILL the router holding the coordinator election and revoke
    /// both its registration lease (so freeze quorums stop counting it)
    /// and its election lease (so a surviving candidate takes over
    /// immediately instead of waiting out the election TTL). Handoffs
    /// created after this run under the new coordinator. With `fast`
    /// false, neither lease is revoked — a true crash whose failover
    /// waits out both TTLs.
    pub async fn kill_coordinator_router(&mut self, fast: bool) -> Result<String> {
        if self.routers.len() < 3 {
            bail!(
                "coordinator kill requires at least 3 routers: the traffic router never \
                 campaigns, so 2 leaves no standby to win the failover election"
            );
        }
        let index = self.coordinator_router_index().await?;
        let (name, mut proc) = self.routers.remove(index);
        proc.kill_now().await;
        if fast {
            etcd::revoke_router_lease(&self.store, &name).await?;
            let held_election =
                etcd::revoke_coordinator_lease_if_held_by(&self.store, &name).await?;
            tracing::info!(router = %name, held_election, "killed coordinator router");
        } else {
            // Registration and election leases linger until their TTLs
            // expire: the survivor stays blind to the death, and no
            // handoff can start until the election lease frees up.
            tracing::info!(router = %name, "crashed coordinator router (leases left to expire)");
        }
        self.retired.push(proc);
        Ok(name)
    }

    /// SIGTERM the router holding the coordinator election — a graceful
    /// exit whose election handover must come from the revoke-on-exit
    /// path, immediately, never from waiting out the lease TTL.
    pub async fn shutdown_coordinator_router(&mut self) -> Result<String> {
        if self.routers.len() < 3 {
            bail!(
                "coordinator shutdown requires at least 3 routers: the traffic router never \
                 campaigns, so 2 leaves no standby to win the failover election"
            );
        }
        let index = self.coordinator_router_index().await?;
        let (name, proc) = self.routers.remove(index);
        proc.sigterm();
        tracing::info!(router = %name, "requested graceful shutdown of coordinator router");
        self.retired.push(proc);
        Ok(name)
    }

    /// Crash-restart the writer: SIGKILL + respawn in the same consumer
    /// group. Uncommitted records are redelivered; the version-guarded
    /// upsert must keep the replay idempotent.
    pub async fn crash_restart_writer(&mut self) -> Result<()> {
        self.infra_mut("writer")?.respawn().await?;
        tracing::info!("crash-restarted writer");
        Ok(())
    }

    /// SIGSTOP the writer — controlled writer-lag injection.
    pub fn pause_writer(&mut self) -> Result<()> {
        self.infra_mut("writer")?.sigstop();
        tracing::info!("paused writer (lag injection)");
        Ok(())
    }

    /// SIGCONT the writer.
    pub fn resume_writer(&mut self) -> Result<()> {
        self.infra_mut("writer")?.sigcont();
        tracing::info!("resumed writer");
        Ok(())
    }

    pub fn changelog_topic(&self) -> &str {
        &self.topic
    }

    pub fn publish_topics(&self) -> Option<&PublishTopics> {
        self.publish_topics.as_ref()
    }

    /// Crash-restart the first publisher: SIGKILL + respawn. Its in-flight
    /// claim rolls back, so the rows stay pending for the other replica or
    /// the respawn, and whatever it had already produced republishes.
    pub async fn crash_restart_publisher(&mut self) -> Result<()> {
        self.infra_mut("publisher-0")?.respawn().await?;
        tracing::info!("crash-restarted publisher");
        Ok(())
    }

    /// Crash-restart the identity service: SIGKILL + respawn. In-flight
    /// RPCs fail unacked; a saga mid-flight is re-driven by the sweeper.
    pub async fn crash_restart_identity(&mut self) -> Result<()> {
        self.infra_mut("identity")?.respawn().await?;
        tracing::info!("crash-restarted identity");
        Ok(())
    }

    /// Wait (up to `deadline`) for a handoff to appear in flight, then
    /// SIGKILL its target pod mid-handoff. Best effort: fast handoffs can
    /// complete between polls, in which case nothing is killed.
    pub async fn kill_handoff_target(&mut self, deadline: Duration) -> Result<Option<String>> {
        let start = Instant::now();
        while start.elapsed() < deadline {
            let handoffs = self.store.list_handoffs().await.unwrap_or_default();
            let target = handoffs
                .iter()
                .find(|h| h.phase != HandoffPhase::Complete)
                .map(|h| h.new_owner.clone());

            if let Some(victim) = target {
                // The target may not be a tracked live leader (e.g. it was
                // already killed); skip and keep watching if so.
                if let Ok((pod_name, mut proc)) = self.remove_leader(&victim) {
                    proc.kill_now().await;
                    tracing::info!(pod = %pod_name, "killed handoff target mid-handoff");
                    etcd::revoke_pod_lease(&self.store, &pod_name).await?;
                    self.retired.push(proc);
                    return Ok(Some(pod_name));
                }
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        tracing::warn!("no in-flight handoff observed within {deadline:?}; nothing killed");
        Ok(None)
    }

    fn remove_leader(&mut self, pod_name: &str) -> Result<(String, ServiceProcess)> {
        let position = self
            .leaders
            .iter()
            .position(|(name, _)| name == pod_name)
            .with_context(|| format!("leader {pod_name} not tracked as live"))?;
        Ok(self.leaders.remove(position))
    }

    fn infra_mut(&mut self, name: &str) -> Result<&mut ServiceProcess> {
        self.infra
            .iter_mut()
            .find(|proc| proc.name() == name)
            .with_context(|| format!("{name} not tracked in stack"))
    }

    /// The live leader owning the most partitions; falls back to the first
    /// live leader when assignments are empty.
    async fn busiest_leader(&self) -> Result<String> {
        if self.leaders.is_empty() {
            bail!("no live leaders to target");
        }

        let assignments = self.store.list_assignments().await.unwrap_or_default();
        let mut counts: HashMap<&str, usize> = HashMap::new();
        for assignment in &assignments {
            *counts.entry(assignment.owner.as_str()).or_default() += 1;
        }

        let busiest = self
            .leaders
            .iter()
            .map(|(name, _)| name)
            .max_by_key(|name| (counts.get(name.as_str()).copied().unwrap_or(0), *name));
        Ok(busiest.expect("leaders is non-empty").clone())
    }

    /// Wait until coordination has converged after chaos: no handoffs in
    /// flight and every partition assigned to a leader whose process is
    /// actually running. Owners are checked against the stack's live
    /// process list rather than etcd registrations — a draining pod stays
    /// registered (with a dead gRPC server) until its lifecycle timeout,
    /// and a briefly-empty handoff list mid-re-drive would otherwise read
    /// as converged. Returns how long convergence took; an already-settled
    /// stack returns immediately. Timing out fails the run: a protocol
    /// that cannot converge is itself a violation, independent of any
    /// data-visibility check.
    pub async fn wait_converged(&mut self, deadline: Duration) -> Result<Duration> {
        let start = Instant::now();
        let mut last_report = String::new();

        loop {
            self.check_alive()?;

            let assignments = self.store.list_assignments().await.unwrap_or_default();
            let handoffs = self.store.list_handoffs().await.unwrap_or_default();
            let live: HashSet<&str> = self.leaders.iter().map(|(name, _)| name.as_str()).collect();
            let dead_owned = assignments
                .iter()
                .filter(|a| !live.contains(a.owner.as_str()))
                .count();

            if handoffs.is_empty()
                && assignments.len() as u32 == self.config.partitions
                && dead_owned == 0
            {
                return Ok(start.elapsed());
            }

            let report = format!(
                "partitions assigned {}/{} ({} on dead pods), handoffs in flight {}",
                assignments.len(),
                self.config.partitions,
                dead_owned,
                handoffs.len()
            );
            if report != last_report {
                tracing::info!("waiting for coordination to converge: {report}");
                last_report = report;
            }
            if start.elapsed() > deadline {
                bail!("coordination did not converge within {deadline:?}: {last_report}");
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
    }

    /// One-line snapshot of coordination state, for chaos event logging.
    pub async fn coordination_report(&self) -> String {
        let pods = self.store.list_pods().await.unwrap_or_default();
        let assignments = self.store.list_assignments().await.unwrap_or_default();
        let handoffs = self.store.list_handoffs().await.unwrap_or_default();
        format!(
            "pods {}, partitions assigned {}/{}, handoffs in flight {}",
            pods.len(),
            assignments.len(),
            self.config.partitions,
            handoffs.len()
        )
    }

    async fn wait_ready(&mut self, partitions: u32, leaders: u32) -> Result<()> {
        let start = Instant::now();
        let mut last_report = String::new();

        loop {
            // Child liveness is checked every probe so a crash-looping
            // service fails the bring-up immediately instead of timing out.
            self.check_alive()?;

            match etcd::check_ready(&self.store, partitions, leaders).await? {
                None => break,
                Some(report) => {
                    if report != last_report {
                        tracing::info!("waiting for coordination: {report}");
                        last_report = report;
                    }
                    if start.elapsed() > READY_DEADLINE {
                        bail!("coordination not ready after {READY_DEADLINE:?}: {last_report}");
                    }
                }
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }

        for i in 0..self.routers.len() {
            let addr = format!("127.0.0.1:{}", ROUTER_GRPC_BASE_PORT + i as u16);
            wait_tcp(&addr, Duration::from_secs(10)).await?;
        }
        if self.identity_url.is_some() {
            wait_tcp(
                &format!("127.0.0.1:{IDENTITY_GRPC_PORT}"),
                Duration::from_secs(10),
            )
            .await?;
        }
        if self.monitor_url.is_some() {
            // The monitor binds after it assigned every partition at the end
            // of the log, so a listening port means no later row is missed.
            wait_tcp(
                &format!("127.0.0.1:{MONITOR_PORT}"),
                Duration::from_secs(30),
            )
            .await?;
        }
        tracing::info!(
            router = %self.router_url,
            elapsed_ms = start.elapsed().as_millis() as u64,
            "stack ready"
        );
        Ok(())
    }

    /// Fail if any spawned service has exited (retired and paused
    /// processes excluded — their state is chaos-induced).
    pub fn check_alive(&mut self) -> Result<()> {
        let mut writer_rebinds = self.writer_rebinds;
        let procs = self
            .infra
            .iter_mut()
            .chain(self.routers.iter_mut().map(|(_, proc)| proc))
            .chain(self.leaders.iter_mut().map(|(_, proc)| proc));
        for proc in procs {
            if let Some(exit) = proc.exited() {
                let clean = exit.as_ref().is_ok_and(|status| status.success());
                let status = match exit {
                    Ok(status) => status.to_string(),
                    Err(e) => format!("unknown ({e})"),
                };
                let logged = if proc.name() == "writer" {
                    std::fs::read_to_string(proc.log_path())
                        .unwrap_or_default()
                        .matches(REBIND_LOG)
                        .count()
                } else {
                    0
                };
                if logged > writer_rebinds && clean {
                    writer_rebinds = logged;
                    proc.restart_exited()?;
                    println!("Migration: the writer exited ({status}) to follow the changelog onto another cluster; restarted it");
                    continue;
                }
                let tail = proc.log_tail(30);
                bail!(
                    "service {} exited ({status}); last log lines:\n{tail}",
                    proc.name()
                );
            }
        }
        self.writer_rebinds = writer_rebinds;
        Ok(())
    }

    pub fn writer_rebinds(&self) -> usize {
        self.writer_rebinds
    }

    fn hosts_of(&self, topic: &str) -> String {
        topic_hosts(&self.config, &self.secondary_topics, topic).to_string()
    }

    fn dump_recent_logs(&self) {
        let procs = self
            .infra
            .iter()
            .chain(self.routers.iter().map(|(_, proc)| proc))
            .chain(self.leaders.iter().map(|(_, proc)| proc));
        for proc in procs {
            tracing::error!(
                service = %proc.name(),
                log = %proc.log_path().display(),
                "--- last log lines ---\n{}",
                proc.log_tail(15)
            );
        }
    }

    pub async fn down(self) -> Result<()> {
        tracing::info!("tearing down stack");
        // Teardown discards all run state (topic deleted below, etcd prefix
        // wiped on the next bring-up), so services stop concurrently with a
        // short grace rather than draining through handoffs.
        let terminations = self
            .infra
            .into_iter()
            .chain(self.routers.into_iter().map(|(_, proc)| proc))
            .chain(self.leaders.into_iter().map(|(_, proc)| proc))
            .chain(self.paused.into_iter().map(|(_, proc)| proc))
            .chain(self.retired)
            .map(|proc| proc.terminate(SHUTDOWN_GRACE));
        futures::future::join_all(terminations).await;

        // Every topic is attempted even when one delete fails, so a failed
        // teardown leaves at most that one topic behind.
        let mut topics: Vec<&str> = self.retired_topics.iter().map(String::as_str).collect();
        topics.push(self.topic.as_str());
        if let Some(publish) = &self.publish_topics {
            topics.push(publish.distinct_ids.as_str());
            topics.push(publish.merge_events.as_str());
        }
        let mut first_error = None;
        for topic in topics {
            let hosts = topic_hosts(&self.config, &self.secondary_topics, topic);
            if let Err(e) = kafka::delete_topic(hosts, topic).await {
                first_error.get_or_insert(e);
            }
        }
        match first_error {
            Some(e) => Err(e),
            None => Ok(()),
        }
    }

    /// Run a changelog migration to its end, with chaos keyed to its phases.
    /// Retirement of the old generation is deferred to `retire_drained`.
    pub async fn migrate(&mut self, chaos: MigrationChaos) -> Result<Duration> {
        // Admission refuses a migration while an earlier generation still drains.
        if !self.pending_retire.is_empty() {
            self.retire_drained().await?;
        }
        let (mut from, revision) = self
            .store
            .get_changelog_config_with_mod_revision()
            .await?
            .context("config/changelog must be seeded")?;
        if chaos.to_secondary && from.cluster.is_none() {
            let primary = ClusterEndpoint {
                name: PRIMARY_CLUSTER.to_string(),
                hosts: self.config.kafka_hosts.clone(),
                tls: false,
            };
            ensure!(
                self.store
                    .set_changelog_cluster(&from, revision, &primary)
                    .await?,
                "recording the live changelog's cluster lost a race"
            );
            from.cluster = Some(primary);
        }
        let generation = self.retired_topics.len() + 2;
        let to_topic = format!("{}_g{generation}", self.topic);
        let to_cluster = if chaos.to_secondary {
            let hosts = self
                .config
                .secondary_kafka_hosts
                .clone()
                .context("a migration onto the secondary cluster needs its hosts")?;
            self.secondary_topics.insert(to_topic.clone());
            Some(ClusterEndpoint {
                name: SECONDARY_CLUSTER.to_string(),
                hosts,
                tls: false,
            })
        } else {
            None
        };
        kafka::create_topic(&self.hosts_of(&to_topic), &to_topic, chaos.to_partitions).await?;
        let migration = MigrationRequest {
            id: format!("harness-g{generation}"),
            from: from.target(),
            to: ChangelogTarget {
                cluster: to_cluster,
                topic: to_topic.clone(),
                partitions: chaos.to_partitions,
            },
            requested_at_ms: now_millis(),
            seen_at_ms: None,
            waiting: Vec::new(),
        };
        // A leader stalled before the request keeps its lease, so the fleet still
        // reads as quiet; the saga starts, holds its partitions and never drains them.
        let mut stalled: Option<String> = None;
        if chaos.stall == Some(StallAt::BeforeStart) {
            let name = self.stall_leader().await?;
            println!("Migration chaos: stalled leader {name} before the request");
            stalled = Some(name);
        }
        ensure!(
            self.store.create_migration_request(&migration).await?,
            "a migration is already requested or in flight"
        );
        // The coordinator starts it once the fleet is quiet.
        let requested = Instant::now();
        // The request is read before the saga: the start creates one and
        // deletes the other in a single transaction, so this order never sees neither.
        loop {
            let waiting = self
                .store
                .get_migration_request_with_mod_revision()
                .await?
                .is_some();
            if self.store.get_migration().await?.is_some() {
                break;
            }
            ensure!(
                waiting,
                "the request was rejected before starting: {:?}",
                self.store
                    .list_migration_history()
                    .await?
                    .into_iter()
                    .find(|m| m.id == migration.id)
            );
            ensure!(
                requested.elapsed() < MIGRATION_DEADLINE,
                "the request did not start within {MIGRATION_DEADLINE:?}"
            );
            tokio::time::sleep(MIGRATION_POLL).await;
        }
        if chaos.pause_writer.is_some() {
            self.pause_writer()?;
        }
        tracing::info!(
            from = %from.topic,
            to = %to_topic,
            partitions = chaos.to_partitions,
            waited_ms = requested.elapsed().as_millis() as u64,
            "changelog migration started"
        );

        let start = Instant::now();
        let mut last_phase = None;
        let mut writer_paused = chaos.pause_writer;
        let mut coordinator_killed = !chaos.kill_coordinator;
        let mut leader_killed = chaos.kill_leader_at.is_none();
        let mut leader_restarted = !chaos.restart_leader;
        let mut sealed_while_stalled = chaos.stall != Some(StallAt::Sealing);
        // A leader stopped at Sealing may already have sealed, which tests nothing, so the
        // victim is stopped once it has drained and must hold no seal ack when Sealing begins.
        let seal_victim_wanted = chaos.kill_leader_at == Some(MigrationPhase::Sealing)
            || chaos.stall == Some(StallAt::Sealing);
        let mut seal_victim: Option<String> = None;
        let mut seal_victim_checked = false;
        loop {
            if let Some(pause) = writer_paused {
                if start.elapsed() >= pause {
                    self.resume_writer()?;
                    writer_paused = None;
                }
            }
            let Some(current) = self.store.get_migration().await? else {
                break;
            };
            if last_phase != Some(current.phase) {
                println!(
                    "Migration {:.1}s: {:?} {}",
                    start.elapsed().as_secs_f64(),
                    current.phase,
                    current.blocking.join("; ")
                );
                last_phase = Some(current.phase);
            }
            let holding = matches!(
                current.phase,
                MigrationPhase::Freezing | MigrationPhase::Draining
            );
            if seal_victim_wanted
                && seal_victim.is_none()
                && current.phase == MigrationPhase::Draining
            {
                let name = self.busiest_leader().await?;
                if self.holder_drained(&name).await? {
                    self.stall_named(&name)?;
                    println!("Migration chaos: stalled leader {name} once drained");
                    seal_victim = Some(name);
                }
            }
            if let Some(name) = seal_victim.clone().filter(|_| !seal_victim_checked) {
                if current.phase == MigrationPhase::Sealing {
                    let sealed = self
                        .store
                        .list_seal_acks()
                        .await?
                        .into_iter()
                        .any(|a| a.migration_id == current.id && a.pod_name == name);
                    ensure!(!sealed, "leader {name} sealed before it stalled");
                    seal_victim_checked = true;
                    if chaos.kill_leader_at == Some(MigrationPhase::Sealing) {
                        self.kill_stalled().await?;
                        println!("Migration chaos: killed leader {name} at Sealing");
                        leader_killed = true;
                    } else {
                        stalled = Some(name);
                    }
                }
            }
            if chaos.stall == Some(StallAt::Sealing) {
                // Past Sealing, the seal grace let its peers seal for it; resume it so Resuming can restart it.
                if stalled.is_some()
                    && matches!(
                        current.phase,
                        MigrationPhase::Resuming | MigrationPhase::Complete
                    )
                {
                    let name = stalled.take().expect("checked above");
                    self.resume_stalled()?;
                    println!(
                        "Migration chaos: the saga flipped while {name} was stalled; resumed it"
                    );
                    sealed_while_stalled = true;
                }
            }
            if !leader_restarted && holding {
                let name = self.restart_leader().await?;
                println!("Migration chaos: crash-restarted leader {name}");
                leader_restarted = true;
            }
            if !coordinator_killed && current.phase == MigrationPhase::Sealing {
                let name = self.kill_coordinator_router(true).await?;
                println!("Migration chaos: killed coordinator router {name}");
                coordinator_killed = true;
            }
            if !leader_killed
                && chaos.kill_leader_at != Some(MigrationPhase::Sealing)
                && Some(current.phase) == chaos.kill_leader_at
            {
                let name = self.kill_leader(true).await?;
                println!("Migration chaos: killed leader {name}");
                leader_killed = true;
            }
            if start.elapsed() > MIGRATION_DEADLINE {
                bail!(
                    "migration did not finish within {MIGRATION_DEADLINE:?}: {current:?}; {}",
                    self.coordination_report().await
                );
            }
            tokio::time::sleep(MIGRATION_POLL).await;
        }
        let saga = start.elapsed();
        // A chaos step the harness never got to apply would let the gate pass vacuously.
        ensure!(
            coordinator_killed && leader_killed && leader_restarted && sealed_while_stalled,
            "a requested chaos step never ran (coordinator killed {coordinator_killed}, \
             leader killed {leader_killed}, leader restarted {leader_restarted}, \
             sealed while stalled {sealed_while_stalled}); slow the coordinator so the phase is observable"
        );
        if let Some(name) = stalled {
            self.resume_stalled()?;
            println!("Migration chaos: resumed stalled leader {name}");
        }
        // The saga never waits for the writer, so the lag it injects outlives the saga.
        if let Some(pause) = writer_paused {
            tokio::time::sleep(pause.saturating_sub(start.elapsed())).await;
            self.resume_writer()?;
            println!(
                "Migration chaos: resumed the writer {:.1}s after the saga started",
                start.elapsed().as_secs_f64()
            );
        }
        let archived = self
            .store
            .list_migration_history()
            .await?
            .into_iter()
            .find(|m| m.id == migration.id)
            .context("the migration record vanished without an archive")?;
        let expected = if chaos.stall == Some(StallAt::BeforeStart) {
            MigrationPhase::Cancelled
        } else {
            MigrationPhase::Complete
        };
        ensure!(
            archived.phase == expected,
            "migration ended in {:?}, expected {expected:?}: {}",
            archived.phase,
            archived.blocking.join("; ")
        );
        if expected == MigrationPhase::Cancelled {
            kafka::delete_topic(&self.hosts_of(&to_topic), &to_topic).await?;
            return Ok(saga);
        }
        self.config.partitions = chaos.to_partitions;
        let old_topic = std::mem::replace(&mut self.topic, to_topic);
        self.retired_topics.push(old_topic.clone());
        self.pending_retire.push((old_topic, Instant::now()));
        Ok(saga)
    }

    /// Wait for the coordinator to retire every old generation on its own,
    /// once the writer reports it drained.
    pub async fn retire_drained(&mut self) -> Result<()> {
        let pending = std::mem::take(&mut self.pending_retire);
        for (old_topic, saga_end) in pending {
            let waited_from = Instant::now();
            loop {
                let draining = self
                    .store
                    .get_changelog_config()
                    .await?
                    .is_some_and(|c| c.draining.iter().any(|g| g.topic == old_topic));
                if !draining {
                    break;
                }
                self.check_alive()?;
                ensure!(
                    waited_from.elapsed() < RETIREMENT_DEADLINE,
                    "the coordinator did not retire {old_topic} within {RETIREMENT_DEADLINE:?}"
                );
                tokio::time::sleep(MIGRATION_POLL).await;
            }
            println!(
                "Migration: {old_topic} retired by the coordinator; checked {:.1}s after the saga, waited {:.1}s",
                saga_end.elapsed().as_secs_f64(),
                waited_from.elapsed().as_secs_f64()
            );
        }
        // The writer re-checks the drain every 2s and flushes every second.
        let moved_at = Instant::now();
        loop {
            if kafka::group_has_committed_offsets(
                &self.hosts_of(&self.topic),
                WRITER_CONSUMER_GROUP,
                &self.topic,
            )
            .await?
            {
                break;
            }
            self.check_alive()?;
            ensure!(
                moved_at.elapsed() < WRITER_MOVE_DEADLINE,
                "the writer did not commit on {} within {WRITER_MOVE_DEADLINE:?}",
                self.topic
            );
            tokio::time::sleep(MIGRATION_POLL).await;
        }
        println!(
            "Migration: the writer committed on {} {:.1}s after the last drain",
            self.topic,
            moved_at.elapsed().as_secs_f64()
        );
        Ok(())
    }
}

/// When migration chaos stalls a leader.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StallAt {
    /// Before the request: its partitions are held and never drain, so the
    /// pre-flip deadline cancels the saga.
    BeforeStart,
    /// Once drained, before Sealing: its peers seal for it after the seal grace, and the saga completes.
    Sealing,
}

pub struct MigrationChaos {
    pub to_partitions: u32,
    pub kill_coordinator: bool,
    /// SIGKILL the busiest leader, lease revoked, when the saga reaches this phase; for Sealing it
    /// is stalled once drained first.
    pub kill_leader_at: Option<MigrationPhase>,
    /// Crash-restart the busiest leader under its own name while the saga holds.
    pub restart_leader: bool,
    /// SIGSTOP the busiest leader with its lease kept.
    pub stall: Option<StallAt>,
    /// Pause the writer for this long as the migration starts.
    pub pause_writer: Option<Duration>,
    pub to_secondary: bool,
}

pub const PRIMARY_CLUSTER: &str = "harness-primary";
pub const SECONDARY_CLUSTER: &str = "harness-secondary";

fn topic_hosts<'a>(
    config: &'a StackConfig,
    secondary_topics: &HashSet<String>,
    topic: &str,
) -> &'a str {
    match &config.secondary_kafka_hosts {
        Some(secondary) if secondary_topics.contains(topic) => secondary,
        _ => &config.kafka_hosts,
    }
}

fn now_millis() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock before the epoch")
        .as_millis() as i64
}

async fn wait_tcp(addr: &str, deadline: Duration) -> Result<()> {
    let start = Instant::now();
    loop {
        if tokio::net::TcpStream::connect(addr).await.is_ok() {
            return Ok(());
        }
        if start.elapsed() > deadline {
            bail!("{addr} not accepting connections after {deadline:?}");
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}
