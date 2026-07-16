use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::HandoffPhase;

mod etcd;
mod kafka;
mod process;

use process::ServiceProcess;

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
const ROUTER_GRPC_BASE_PORT: u16 = 24054;
const LEADER_GRPC_BASE_PORT: u16 = 24060;
const REPLICA_METRICS_PORT: u16 = 24151;
const WRITER_METRICS_PORT: u16 = 24153;
const ROUTER_METRICS_BASE_PORT: u16 = 24154;
const LEADER_METRICS_BASE_PORT: u16 = 24160;
const MAX_ROUTERS: u32 = 4;

const ETCD_PREFIX: &str = "/personhog-test-harness/";
const READY_DEADLINE: Duration = Duration::from_secs(90);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

pub struct StackConfig {
    /// Directory containing the service binaries (the cargo target dir).
    pub bin_dir: PathBuf,
    pub leaders: u32,
    pub routers: u32,
    pub partitions: u32,
    pub kafka_hosts: String,
    pub etcd_endpoints: String,
    pub persons_db_url: String,
    /// Writer flush cadence. Short by default so gate quiesce is quick.
    pub writer_flush_interval_ms: u64,
    /// The table the writer upserts into.
    pub pg_target_table: String,
    /// Leader in-memory cache capacity (entries). Lower it below the seeded
    /// person count to put the cache under eviction pressure.
    pub cache_memory_capacity: usize,
    /// etcd lease TTL for leaders, in seconds. Bounds how long a crashed
    /// (unrevoked) leader stays the registered owner.
    pub leader_lease_ttl: i64,
}

/// A locally-spawned personhog stack: replica, writer, N leaders, and M
/// leader-mode routers (each hosting a coordinator candidate), all pointed
/// at the docker-compose Kafka/etcd/Postgres but isolated from the dev
/// stack via their own ports, etcd prefix, and per-run changelog topic.
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
    pub router_url: String,
    pub log_dir: PathBuf,
}

impl Stack {
    pub async fn up(config: StackConfig) -> Result<Self> {
        if config.routers == 0 || config.routers > MAX_ROUTERS {
            bail!("--routers must be between 1 and {MAX_ROUTERS}");
        }

        let run_id = chrono::Utc::now().format("%Y%m%d_%H%M%S").to_string();
        let topic = format!("personhog_test_harness_{run_id}");
        let log_dir = config.bin_dir.join("harness-logs").join(&run_id);
        fs::create_dir_all(&log_dir)
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
            routers = config.routers,
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
                    "personhog-test-harness-writer".to_string(),
                ),
                ("PG_TARGET_TABLE", config.pg_target_table.clone()),
                (
                    "FLUSH_INTERVAL_MS",
                    config.writer_flush_interval_ms.to_string(),
                ),
                ("METRICS_PORT", WRITER_METRICS_PORT.to_string()),
            ],
            &log_dir,
        )?);

        // The first router must win the coordinator election so chaos that
        // targets "the coordinator" is deterministic: spawn it alone, wait
        // for it to acquire leadership, then bring up the rest.
        let mut routers = Vec::new();
        for i in 0..config.routers {
            if i == 1 {
                etcd::wait_for_leader(&store, "harness-router-0", Duration::from_secs(15)).await?;
            }
            let name = format!("harness-router-{i}");
            let proc = ServiceProcess::spawn(
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
                    ("POD_NAME", name.clone()),
                    (
                        "METRICS_PORT",
                        (ROUTER_METRICS_BASE_PORT + i as u16).to_string(),
                    ),
                ],
                &log_dir,
            )?;
            routers.push((name, proc));
        }

        // Traffic targets the last router: the first spawned usually wins
        // the coordinator election, so a coordinator kill (which targets
        // the first) leaves the traffic path intact.
        let traffic_router_port = ROUTER_GRPC_BASE_PORT + (config.routers - 1) as u16;
        let router_url = format!("http://127.0.0.1:{traffic_router_port}");

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
        // Heartbeats must land well inside the lease window or a healthy
        // pod's lease expires between renewals.
        let heartbeat_secs = (self.config.leader_lease_ttl / 3).max(1);
        let proc = ServiceProcess::spawn(
            &format!("leader-{index}"),
            &self.config.bin_dir.join("personhog-leader"),
            &[
                ("GRPC_ADDRESS", pod_name.clone()),
                ("POD_NAME", pod_name.clone()),
                ("LEASE_TTL", self.config.leader_lease_ttl.to_string()),
                ("HEARTBEAT_INTERVAL_SECS", heartbeat_secs.to_string()),
                (
                    "CACHE_MEMORY_CAPACITY",
                    self.config.cache_memory_capacity.to_string(),
                ),
                ("ETCD_ENDPOINTS", self.config.etcd_endpoints.clone()),
                ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
                ("KAFKA_HOSTS", self.config.kafka_hosts.clone()),
                ("KAFKA_PERSON_STATE_TOPIC", self.topic.clone()),
                // Must match the spawned writer's consumer group or the
                // leader's committed-offset queries (warming ranges, dirty
                // index pruning) silently see no progress at all.
                (
                    "WRITER_CONSUMER_GROUP",
                    "personhog-test-harness-writer".to_string(),
                ),
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
        let (pod_name, proc) = self.remove_leader(&victim)?;

        proc.sigterm();
        tracing::info!(pod = %pod_name, "requested graceful shutdown");
        self.retired.push(proc);
        Ok(pod_name)
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

    /// SIGCONT the paused zombie. It wakes believing it still owns its
    /// partitions; whatever it does next (self-fence, exit, re-register)
    /// must not corrupt state that has moved to the new owner.
    pub fn resume_zombie(&mut self) -> Result<String> {
        let (pod_name, proc) = self
            .paused
            .pop()
            .context("no paused zombie leader to resume")?;
        proc.sigcont();
        tracing::info!(pod = %pod_name, "SIGCONTed zombie leader");
        self.retired.push(proc);
        Ok(pod_name)
    }

    /// SIGKILL the first-spawned router — the coordinator, since bring-up
    /// waits for it to win the election — and revoke both its registration
    /// lease (so freeze quorums stop counting it) and its election lease
    /// (so a surviving router takes over immediately instead of waiting
    /// out the election TTL). Handoffs created after this run under the
    /// new coordinator. With `fast` false, neither lease is revoked — a
    /// true crash whose failover waits out both TTLs.
    pub async fn kill_coordinator_router(&mut self, fast: bool) -> Result<String> {
        if self.routers.len() < 2 {
            bail!("coordinator kill requires at least 2 routers");
        }
        let (name, mut proc) = self.routers.remove(0);
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

    /// SIGTERM the first router (the presumed coordinator) — a graceful
    /// exit whose election handover must come from the revoke-on-exit
    /// path, immediately, never from waiting out the lease TTL.
    pub fn shutdown_coordinator_router(&mut self) -> Result<String> {
        if self.routers.len() < 2 {
            bail!("coordinator shutdown requires at least 2 routers");
        }
        let (name, proc) = self.routers.remove(0);
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
        let procs = self
            .infra
            .iter_mut()
            .chain(self.routers.iter_mut().map(|(_, proc)| proc))
            .chain(self.leaders.iter_mut().map(|(_, proc)| proc));
        for proc in procs {
            if let Some(status) = proc.exited() {
                let tail = proc.log_tail(30);
                bail!(
                    "service {} exited ({status}); last log lines:\n{tail}",
                    proc.name()
                );
            }
        }
        Ok(())
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

        kafka::delete_topic(&self.config.kafka_hosts, &self.topic).await?;
        Ok(())
    }
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
