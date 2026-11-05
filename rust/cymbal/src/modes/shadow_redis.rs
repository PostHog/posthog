use std::{
    future::Future,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Mutex, OnceLock,
    },
    time::{Duration, Instant},
};

use tokio::sync::Semaphore;

use common_redis::{Client, CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat};
use tracing::warn;

use crate::modes::processing::redis_heal::{is_connection_error, HealGate};

const SHADOW_DEADLINE: Duration = Duration::from_millis(200);
const MAX_IN_FLIGHT_SHADOW_WRITES: usize = 128;
const SHADOW_RECOVERY_INTERVAL: Duration = Duration::from_secs(5);
const SHADOW_RECOVERY_DEADLINE: Duration = Duration::from_secs(2);
const SHADOW_WARN_INTERVAL_MS: u64 = 30_000;
static SHADOW_PERMITS: OnceLock<Arc<Semaphore>> = OnceLock::new();
static SHADOW_CIRCUIT: OnceLock<Arc<ShadowCircuit>> = OnceLock::new();
static SHADOW_HEAL_GATE: OnceLock<HealGate> = OnceLock::new();
static WARN_EPOCH: OnceLock<Instant> = OnceLock::new();
static LAST_SHADOW_WARNING_MS: AtomicU64 = AtomicU64::new(0);

#[cfg(test)]
tokio::task_local! {
    static TEST_SHADOW_CIRCUIT: Arc<ShadowCircuit>;
}

#[cfg(test)]
pub(crate) async fn with_test_circuit<T>(future: impl Future<Output = T>) -> T {
    TEST_SHADOW_CIRCUIT
        .scope(Arc::new(ShadowCircuit::new()), future)
        .await
}

fn shadow_circuit() -> Arc<ShadowCircuit> {
    #[cfg(test)]
    if let Ok(circuit) = TEST_SHADOW_CIRCUIT.try_with(Arc::clone) {
        return circuit;
    }
    SHADOW_CIRCUIT
        .get_or_init(|| Arc::new(ShadowCircuit::new()))
        .clone()
}

pub async fn connect(
    url: Option<&str>,
    primary_urls: &[&str],
    format: RedisValueFormat,
    response_timeout_ms: u64,
    connection_timeout_ms: u64,
) -> Option<Arc<RedisClient>> {
    let url = url.filter(|url| !url.trim().is_empty())?;
    if primary_urls
        .iter()
        .any(|primary| same_endpoint(url, primary))
    {
        metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => "connect", "outcome" => "same_endpoint").increment(1);
        warn!("shadow Redis URL matches a primary Redis URL; shadow writes disabled");
        return None;
    }
    match RedisClient::with_config(
        url.to_string(),
        CompressionConfig::disabled(),
        format,
        Some(Duration::from_millis(shadow_timeout_ms(
            response_timeout_ms,
            200,
        ))),
        Some(Duration::from_millis(shadow_timeout_ms(
            connection_timeout_ms,
            1000,
        ))),
    )
    .await
    {
        Ok(client) => {
            metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => "connect", "outcome" => "ok").increment(1);
            Some(Arc::new(client))
        }
        Err(error) => {
            metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => "connect", "outcome" => "error").increment(1);
            warn!(%error, "shadow Redis connection unavailable; primary remains active");
            None
        }
    }
}

fn shadow_timeout_ms(configured: u64, cap: u64) -> u64 {
    if configured == 0 {
        cap
    } else {
        configured.min(cap)
    }
}

fn same_endpoint(shadow: &str, primary: &str) -> bool {
    shadow == primary
        || matches!((redis_endpoint(shadow), redis_endpoint(primary)), (Some(a), Some(b)) if a == b)
}

#[derive(PartialEq, Eq)]
enum RedisEndpoint {
    Tcp(String, u16, i64),
    Unix(std::path::PathBuf, i64),
}

fn redis_endpoint(url: &str) -> Option<RedisEndpoint> {
    let client = redis::Client::open(url).ok()?;
    let info = client.get_connection_info();
    let (host, port) = match &info.addr {
        redis::ConnectionAddr::Tcp(host, port) => (host, *port),
        redis::ConnectionAddr::TcpTls { host, port, .. } => (host, *port),
        redis::ConnectionAddr::Unix(path) => {
            return Some(RedisEndpoint::Unix(path.clone(), info.redis.db));
        }
    };
    let host = host.trim_end_matches('.').to_ascii_lowercase();
    let host = match host.as_str() {
        "localhost" | "::1" | "[::1]" => "127.0.0.1".to_string(),
        _ => host,
    };
    Some(RedisEndpoint::Tcp(host, port, info.redis.db))
}

fn should_warn(last: &AtomicU64, now_ms: u64) -> bool {
    let now = now_ms.saturating_add(1);
    let previous = last.load(Ordering::Relaxed);
    (previous == 0 || now.saturating_sub(previous) >= SHADOW_WARN_INTERVAL_MS)
        && last
            .compare_exchange(previous, now, Ordering::Relaxed, Ordering::Relaxed)
            .is_ok()
}

fn warn_for_shadow_failure() -> bool {
    let elapsed_ms = WARN_EPOCH.get_or_init(Instant::now).elapsed().as_millis() as u64;
    should_warn(&LAST_SHADOW_WARNING_MS, elapsed_ms)
}

struct RecoveryState {
    generation: u64,
    next_attempt: Instant,
}

// A timed-out request can stay queued in redis-rs. Block writes until a new connection replaces it.
struct ShadowCircuit {
    blocked: AtomicBool,
    generation: AtomicU64,
    recovery: Mutex<RecoveryState>,
}

impl ShadowCircuit {
    fn new() -> Self {
        Self {
            blocked: AtomicBool::new(false),
            generation: AtomicU64::new(0),
            recovery: Mutex::new(RecoveryState {
                generation: 0,
                next_attempt: Instant::now(),
            }),
        }
    }

    fn trip(self: &Arc<Self>, generation: u64, heal: impl Future<Output = bool> + Send + 'static) {
        let mut recovery = self.recovery.lock().unwrap();
        if recovery.generation != generation {
            return;
        }
        self.blocked.store(true, Ordering::Release);
        self.schedule_recovery(&mut recovery, heal);
    }

    fn retry(self: &Arc<Self>, heal: impl Future<Output = bool> + Send + 'static) {
        let mut recovery = self.recovery.lock().unwrap();
        self.schedule_recovery(&mut recovery, heal);
    }

    fn schedule_recovery(
        self: &Arc<Self>,
        recovery: &mut RecoveryState,
        heal: impl Future<Output = bool> + Send + 'static,
    ) {
        if Instant::now() < recovery.next_attempt {
            return;
        }
        recovery.next_attempt = Instant::now() + SHADOW_RECOVERY_INTERVAL;
        let circuit = self.clone();
        tokio::spawn(async move {
            if let Ok(true) = tokio::time::timeout(SHADOW_RECOVERY_DEADLINE, heal).await {
                let mut recovery = circuit.recovery.lock().unwrap();
                recovery.generation += 1;
                circuit
                    .generation
                    .store(recovery.generation, Ordering::Release);
                circuit.blocked.store(false, Ordering::Release);
                metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => "reconnect", "outcome" => "ok").increment(1);
            } else {
                metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => "reconnect", "outcome" => "error").increment(1);
            }
        });
    }
}

pub fn submit<T: Send + 'static>(
    operation: &'static str,
    write: impl Future<Output = Result<T, CustomRedisError>> + Send + 'static,
    heal: impl Future<Output = bool> + Send + 'static,
) {
    let permits =
        SHADOW_PERMITS.get_or_init(|| Arc::new(Semaphore::new(MAX_IN_FLIGHT_SHADOW_WRITES)));
    let circuit = shadow_circuit();
    submit_with_permits(permits, &circuit, operation, write, heal);
}

fn submit_with_permits<T: Send + 'static>(
    permits: &Arc<Semaphore>,
    circuit: &Arc<ShadowCircuit>,
    operation: &'static str,
    write: impl Future<Output = Result<T, CustomRedisError>> + Send + 'static,
    heal: impl Future<Output = bool> + Send + 'static,
) {
    if circuit.blocked.load(Ordering::Acquire) {
        metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "circuit_open").increment(1);
        circuit.retry(heal);
        return;
    }
    let generation = circuit.generation.load(Ordering::Acquire);
    let Ok(permit) = permits.clone().try_acquire_owned() else {
        metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "dropped").increment(1);
        return;
    };
    let circuit = circuit.clone();
    tokio::spawn(async move {
        let _permit = permit;
        match tokio::time::timeout(SHADOW_DEADLINE, write).await {
            Ok(Ok(_)) => metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "ok").increment(1),
            Ok(Err(error)) => {
                metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "error").increment(1);
                if warn_for_shadow_failure() {
                    warn!(%error, operation, "shadow Redis write failed");
                }
                if matches!(error, CustomRedisError::Timeout) {
                    circuit.trip(generation, heal);
                } else if is_connection_error(&error) {
                    SHADOW_HEAL_GATE.get_or_init(HealGate::new).spawn_heal(async move {
                        let _ = heal.await;
                    });
                }
            }
            Err(_) => {
                metrics::counter!("cymbal_shadow_redis_operations_total", "operation" => operation, "outcome" => "timeout").increment(1);
                if warn_for_shadow_failure() {
                    warn!(operation, "shadow Redis write timed out");
                }
                circuit.trip(generation, heal);
            }
        }
    });
}

pub fn set_bytes(
    shadow: Option<&Arc<dyn Client + Send + Sync>>,
    key: String,
    payload: Vec<u8>,
    ttl_seconds: u64,
) {
    if let Some(shadow) = shadow {
        let shadow = shadow.clone();
        let healing = shadow.clone();
        submit(
            "event_properties",
            async move { shadow.set_bytes(key, payload, Some(ttl_seconds)).await },
            async move { healing.reconnect().await },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use metrics_util::debugging::DebuggingRecorder;

    #[tokio::test]
    async fn exact_primary_url_cannot_be_shadowed() {
        let shadow = connect(
            Some("redis://localhost:6379/"),
            &["redis://localhost:6379/"],
            RedisValueFormat::Utf8,
            100,
            100,
        )
        .await;
        assert!(shadow.is_none());
    }

    #[test]
    fn equivalent_primary_urls_cannot_be_shadowed() {
        assert!(same_endpoint(
            "redis://primary-host:6379/0",
            "redis://primary-host:6379"
        ));
        assert!(same_endpoint(
            "redis://localhost",
            "redis://127.0.0.1:6379/"
        ));
        assert!(same_endpoint(
            "redis+unix:///var/run/redis/redis.sock",
            "unix:///var/run/redis/redis.sock"
        ));
        assert!(same_endpoint(
            "rediss://PRIMARY-HOST:6379/",
            "redis://primary-host:6379/0"
        ));
        assert!(!same_endpoint(
            "redis://primary-host:6379/1",
            "redis://primary-host:6379/0"
        ));
        assert!(!same_endpoint(
            "redis://new-host:6379",
            "redis://primary-host:6379"
        ));
    }

    #[test]
    fn zero_primary_timeout_uses_bounded_shadow_timeout() {
        assert_eq!(shadow_timeout_ms(0, 200), 200);
        assert_eq!(shadow_timeout_ms(0, 1000), 1000);
        assert_eq!(shadow_timeout_ms(100, 200), 100);
        assert_eq!(shadow_timeout_ms(5000, 1000), 1000);
    }

    #[test]
    fn repeated_failures_do_not_repeat_warnings() {
        let last = AtomicU64::new(0);
        assert!(should_warn(&last, 0));
        assert!(!should_warn(&last, 1));
        assert!(!should_warn(&last, SHADOW_WARN_INTERVAL_MS - 1));
        assert!(should_warn(&last, SHADOW_WARN_INTERVAL_MS));
    }

    #[tokio::test]
    async fn timeout_blocks_new_writes_until_reconnect_succeeds() {
        let permits = Arc::new(Semaphore::new(2));
        let circuit = Arc::new(ShadowCircuit::new());
        let (started_tx, started_rx) = tokio::sync::oneshot::channel();
        let (resume_tx, resume_rx) = tokio::sync::oneshot::channel();
        submit_with_permits(
            &permits,
            &circuit,
            "test_timeout",
            std::future::pending::<Result<(), CustomRedisError>>(),
            async move {
                let _ = started_tx.send(());
                let _ = resume_rx.await;
                true
            },
        );
        tokio::time::timeout(Duration::from_secs(1), started_rx)
            .await
            .unwrap()
            .unwrap();
        assert!(circuit.blocked.load(Ordering::Acquire));

        let called = Arc::new(AtomicBool::new(false));
        let rejected = called.clone();
        submit_with_permits(
            &permits,
            &circuit,
            "test_blocked",
            async move {
                rejected.store(true, Ordering::Release);
                Ok::<(), CustomRedisError>(())
            },
            async { true },
        );
        assert!(!called.load(Ordering::Acquire));

        resume_tx.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(1), async {
            while circuit.blocked.load(Ordering::Acquire) {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(circuit.generation.load(Ordering::Acquire), 1);
    }

    #[tokio::test]
    async fn failed_reconnect_keeps_shadow_circuit_open() {
        let permits = Arc::new(Semaphore::new(1));
        let circuit = Arc::new(ShadowCircuit::new());
        let (tried_tx, tried_rx) = tokio::sync::oneshot::channel();
        submit_with_permits(
            &permits,
            &circuit,
            "test_failure",
            async { Err::<(), _>(CustomRedisError::Timeout) },
            async move {
                let _ = tried_tx.send(());
                false
            },
        );
        tokio::time::timeout(Duration::from_secs(1), tried_rx)
            .await
            .unwrap()
            .unwrap();
        assert!(circuit.blocked.load(Ordering::Acquire));
        circuit.recovery.lock().unwrap().next_attempt = Instant::now();
        let (recovered_tx, recovered_rx) = tokio::sync::oneshot::channel();
        submit_with_permits(
            &permits,
            &circuit,
            "test_retry",
            async { Ok::<(), CustomRedisError>(()) },
            async move {
                let _ = recovered_tx.send(());
                true
            },
        );
        tokio::time::timeout(Duration::from_secs(1), recovered_rx)
            .await
            .unwrap()
            .unwrap();
        tokio::time::timeout(Duration::from_secs(1), async {
            while circuit.blocked.load(Ordering::Acquire) {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
    }

    #[test]
    fn saturated_shadow_capacity_records_dropped_write() {
        let recorder = DebuggingRecorder::new();
        metrics::with_local_recorder(&recorder, || {
            submit_with_permits(
                &Arc::new(Semaphore::new(0)),
                &Arc::new(ShadowCircuit::new()),
                "issue_buckets",
                async { Ok::<(), CustomRedisError>(()) },
                async { true },
            );
        });
        let snapshot = recorder.snapshotter().snapshot().into_vec();
        assert!(snapshot.iter().any(|(key, _, _, _)| {
            key.key().name() == "cymbal_shadow_redis_operations_total"
                && key
                    .key()
                    .labels()
                    .any(|label| label.key() == "outcome" && label.value() == "dropped")
        }));
    }
}
