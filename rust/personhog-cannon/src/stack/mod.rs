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
}

/// A locally-spawned personhog stack: replica, writer, N leaders, and a
/// leader-mode router (which hosts the coordinator), all pointed at the
/// docker-compose Kafka/etcd/Postgres but isolated from the dev stack via
/// their own ports, etcd prefix, and per-run changelog topic.
pub struct Stack {
    procs: Vec<ServiceProcess>,
    store: PersonhogStore,
    kafka_hosts: String,
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

        let mut procs = Vec::new();

        procs.push(ServiceProcess::spawn(
            "replica",
            &config.bin_dir.join("personhog-replica"),
            &[
                ("GRPC_ADDRESS", format!("127.0.0.1:{REPLICA_GRPC_PORT}")),
                ("PRIMARY_DATABASE_URL", config.persons_db_url.clone()),
                ("METRICS_PORT", REPLICA_METRICS_PORT.to_string()),
            ],
            &log_dir,
        )?);

        procs.push(ServiceProcess::spawn(
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

        for i in 0..config.leaders {
            let grpc_port = LEADER_GRPC_BASE_PORT + i as u16;
            // POD_NAME carries the explicit host:port so the router's
            // resolver dials each local leader on its own port.
            let pod_name = format!("127.0.0.1:{grpc_port}");
            procs.push(ServiceProcess::spawn(
                &format!("leader-{i}"),
                &config.bin_dir.join("personhog-leader"),
                &[
                    ("GRPC_ADDRESS", pod_name.clone()),
                    ("POD_NAME", pod_name),
                    ("CACHE_MEMORY_CAPACITY", "100000".to_string()),
                    ("ETCD_ENDPOINTS", config.etcd_endpoints.clone()),
                    ("ETCD_PREFIX", ETCD_PREFIX.to_string()),
                    ("KAFKA_HOSTS", config.kafka_hosts.clone()),
                    ("KAFKA_PERSON_STATE_TOPIC", topic.clone()),
                    ("FALLBACK_DATABASE_URL", config.persons_db_url.clone()),
                    (
                        "METRICS_PORT",
                        (LEADER_METRICS_BASE_PORT + i as u16).to_string(),
                    ),
                ],
                &log_dir,
            )?);
        }

        procs.push(ServiceProcess::spawn(
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
            procs,
            store,
            kafka_hosts: config.kafka_hosts,
            topic,
            router_url,
            log_dir,
        };

        stack
            .wait_ready(config.partitions, config.leaders)
            .await
            .inspect_err(|_| stack.dump_recent_logs())?;

        Ok(stack)
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

    /// Fail if any spawned service has exited.
    pub fn check_alive(&mut self) -> Result<()> {
        for proc in &mut self.procs {
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
        for proc in &self.procs {
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
            .procs
            .into_iter()
            .map(|proc| proc.terminate(SHUTDOWN_GRACE));
        futures::future::join_all(terminations).await;

        kafka::delete_topic(&self.kafka_hosts, &self.topic).await?;
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
