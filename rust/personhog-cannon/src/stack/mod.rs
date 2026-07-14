use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use personhog_coordination::store::PersonhogStore;

mod etcd;
mod kafka;
mod process;

use process::ServiceProcess;

/// Ports sit in their own range so a harness stack can run alongside the
/// dev stack (gRPC 50051-50054, metrics 9100-9105) without collisions.
const REPLICA_GRPC_PORT: u16 = 51051;
const ROUTER_GRPC_PORT: u16 = 51054;
const LEADER_GRPC_BASE_PORT: u16 = 51060;
const REPLICA_METRICS_PORT: u16 = 51151;
const WRITER_METRICS_PORT: u16 = 51153;
const ROUTER_METRICS_PORT: u16 = 51154;
const LEADER_METRICS_BASE_PORT: u16 = 51160;

const ETCD_PREFIX: &str = "/personhog-cannon/";
const READY_DEADLINE: Duration = Duration::from_secs(90);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

pub struct StackConfig {
    /// Directory containing the service binaries (the cargo target dir).
    pub bin_dir: PathBuf,
    pub leaders: u32,
    pub partitions: u32,
    pub kafka_hosts: String,
    pub etcd_endpoints: String,
    pub persons_db_url: String,
    /// Writer flush cadence. Short by default so gate quiesce is quick.
    pub writer_flush_interval_ms: u64,
    /// Leader in-memory cache capacity (entries). Lower it below the seeded
    /// person count to put the cache under eviction pressure.
    pub cache_memory_capacity: usize,
}

/// A locally-spawned personhog stack: replica, writer, N leaders, and a
/// leader-mode router (which hosts the coordinator), all pointed at the
/// docker-compose Kafka/etcd/Postgres but isolated from the dev stack via
/// their own ports, etcd prefix, and per-run changelog topic.
pub struct Stack {
    config: StackConfig,
    infra: Vec<ServiceProcess>,
    /// Live leaders, keyed by the pod name they registered with.
    leaders: Vec<(String, ServiceProcess)>,
    /// Leaders removed by chaos (killed or shutting down); their exit is
    /// expected, so they are excluded from liveness checks.
    retired: Vec<ServiceProcess>,
    next_leader_index: u32,
    store: PersonhogStore,
    topic: String,
    pub router_url: String,
    pub log_dir: PathBuf,
}

impl Stack {
    pub async fn up(config: StackConfig) -> Result<Self> {
        let run_id = chrono::Utc::now().format("%Y%m%d_%H%M%S").to_string();
        let topic = format!("personhog_cannon_{run_id}");
        let log_dir = config.bin_dir.join("cannon-logs").join(&run_id);
        std::fs::create_dir_all(&log_dir)
            .with_context(|| format!("creating log dir {}", log_dir.display()))?;

        let binaries = [
            "personhog-replica",
            "personhog-router",
            "personhog-leader",
            "personhog-writer",
        ];
        for bin in binaries {
            let path = config.bin_dir.join(bin);
            if !path.exists() {
                bail!(
                    "{} not found — build the stack first:\n  cargo build -p personhog-replica \
                     -p personhog-router -p personhog-leader -p personhog-writer",
                    path.display()
                );
            }
        }

        tracing::info!(
            leaders = config.leaders,
            partitions = config.partitions,
            topic,
            log_dir = %log_dir.display(),
            "bringing up stack"
        );

        let store = etcd::connect(&config.etcd_endpoints, ETCD_PREFIX).await?;
        etcd::reset(&store, config.partitions).await?;
        kafka::create_topic(&config.kafka_hosts, &topic, config.partitions).await?;

        let mut infra = Vec::new();

        infra.push(ServiceProcess::spawn(
            "replica",
            &config.bin_dir.join("personhog-replica"),
            &[
                ("GRPC_ADDRESS", format!("127.0.0.1:{REPLICA_GRPC_PORT}")),
                ("PRIMARY_DATABASE_URL", config.persons_db_url.clone()),
                ("METRICS_PORT", REPLICA_METRICS_PORT.to_string()),
            ],
            &log_dir,
        )?);

        infra.push(ServiceProcess::spawn(
            "writer",
            &config.bin_dir.join("personhog-writer"),
            &[
                ("DATABASE_URL", config.persons_db_url.clone()),
                ("KAFKA_HOSTS", config.kafka_hosts.clone()),
                ("KAFKA_TOPIC", topic.clone()),
                (
                    "KAFKA_CONSUMER_GROUP",
                    "personhog-cannon-writer".to_string(),
                ),
                ("PG_TARGET_TABLE", "posthog_person".to_string()),
                (
                    "FLUSH_INTERVAL_MS",
                    config.writer_flush_interval_ms.to_string(),
                ),
                ("METRICS_PORT", WRITER_METRICS_PORT.to_string()),
            ],
            &log_dir,
        )?);

        infra.push(ServiceProcess::spawn(
            "router-leader",
            &config.bin_dir.join("personhog-router"),
            &[
                ("ROUTER_MODE", "leader".to_string()),
                ("GRPC_ADDRESS", format!("127.0.0.1:{ROUTER_GRPC_PORT}")),
                (
                    "REPLICA_URL",
                    format!("http://127.0.0.1:{REPLICA_GRPC_PORT}"),
                ),
                ("ETCD_ENDPOINTS", config.etcd_endpoints.clone()),
                ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
                ("BACKEND_TIMEOUT_MS", "5000".to_string()),
                ("POD_NAME", "cannon-router".to_string()),
                ("METRICS_PORT", ROUTER_METRICS_PORT.to_string()),
            ],
            &log_dir,
        )?);

        let router_url = format!("http://127.0.0.1:{ROUTER_GRPC_PORT}");
        let mut stack = Self {
            config,
            infra,
            leaders: Vec::new(),
            retired: Vec::new(),
            next_leader_index: 0,
            store,
            topic,
            router_url,
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

    /// Spawn one more leader. The pod registers with an explicit host:port
    /// name, which the router's resolver dials as-is.
    pub fn spawn_leader(&mut self) -> Result<String> {
        let index = self.next_leader_index;
        self.next_leader_index += 1;

        let grpc_port = LEADER_GRPC_BASE_PORT + index as u16;
        let pod_name = format!("127.0.0.1:{grpc_port}");
        let proc = ServiceProcess::spawn(
            &format!("leader-{index}"),
            &self.config.bin_dir.join("personhog-leader"),
            &[
                ("GRPC_ADDRESS", pod_name.clone()),
                ("POD_NAME", pod_name.clone()),
                (
                    "CACHE_MEMORY_CAPACITY",
                    self.config.cache_memory_capacity.to_string(),
                ),
                ("ETCD_ENDPOINTS", self.config.etcd_endpoints.clone()),
                ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
                ("KAFKA_HOSTS", self.config.kafka_hosts.clone()),
                ("KAFKA_PERSON_STATE_TOPIC", self.topic.clone()),
                ("FALLBACK_DATABASE_URL", self.config.persons_db_url.clone()),
                (
                    "METRICS_PORT",
                    (LEADER_METRICS_BASE_PORT + index as u16).to_string(),
                ),
            ],
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
        let position = self
            .leaders
            .iter()
            .position(|(name, _)| *name == victim)
            .context("victim leader not tracked")?;
        let (pod_name, mut proc) = self.leaders.remove(position);

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
        let position = self
            .leaders
            .iter()
            .position(|(name, _)| *name == victim)
            .context("victim leader not tracked")?;
        let (pod_name, proc) = self.leaders.remove(position);

        proc.sigterm();
        tracing::info!(pod = %pod_name, "requested graceful shutdown");
        self.retired.push(proc);
        Ok(pod_name)
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
        let start = std::time::Instant::now();
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

        wait_tcp(
            &format!("127.0.0.1:{ROUTER_GRPC_PORT}"),
            Duration::from_secs(10),
        )
        .await?;
        tracing::info!(
            router = %self.router_url,
            elapsed_ms = start.elapsed().as_millis() as u64,
            "stack ready"
        );
        Ok(())
    }

    /// Fail if any spawned service has exited (retired leaders excluded —
    /// their exit is the point).
    pub fn check_alive(&mut self) -> Result<()> {
        let procs = self
            .infra
            .iter_mut()
            .chain(self.leaders.iter_mut().map(|(_, proc)| proc));
        for proc in procs {
            if let Some(status) = proc.exited() {
                let tail = proc.log_tail(30);
                bail!(
                    "service {} exited ({status}); last log lines:\n{tail}",
                    proc.name
                );
            }
        }
        Ok(())
    }

    fn dump_recent_logs(&self) {
        let procs = self
            .infra
            .iter()
            .chain(self.leaders.iter().map(|(_, proc)| proc));
        for proc in procs {
            tracing::error!(
                service = %proc.name,
                log = %proc.log_path.display(),
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
            .chain(self.leaders.into_iter().map(|(_, proc)| proc))
            .chain(self.retired)
            .map(|proc| proc.terminate(SHUTDOWN_GRACE));
        futures::future::join_all(terminations).await;

        kafka::delete_topic(&self.config.kafka_hosts, &self.topic).await?;
        Ok(())
    }
}

async fn wait_tcp(addr: &str, deadline: Duration) -> Result<()> {
    let start = std::time::Instant::now();
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
