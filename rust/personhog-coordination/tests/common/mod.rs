#![allow(dead_code)]

use personhog_coordination::authority::AuthorityClock;
use std::collections::{HashMap, HashSet};
use std::future::{pending, Future};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex as StdMutex, RwLock as StdRwLock};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use tokio::io::copy_bidirectional;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{Mutex, Notify, RwLock};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use personhog_coordination::coordinator::{Coordinator, CoordinatorConfig};
use personhog_coordination::error::Result;
use personhog_coordination::pod::{HandoffHandler, PodConfig, PodHandle};
use personhog_coordination::routing_table::{RoutingTable, RoutingTableConfig, StashHandler};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::strategy::AssignmentStrategy;

pub const ETCD_ENDPOINT: &str = "http://localhost:2379";
pub const WAIT_TIMEOUT: Duration = Duration::from_secs(10);
pub const POLL_INTERVAL: Duration = Duration::from_millis(100);

pub async fn test_store(test_name: &str) -> Arc<PersonhogStore> {
    test_store_with_prefix(test_name).await.0
}

/// Like `test_store`, but also returns the generated etcd prefix so tests
/// can inspect or manipulate raw keys (e.g. revoking a component's lease).
pub async fn test_store_with_prefix(test_name: &str) -> (Arc<PersonhogStore>, String) {
    let prefix = format!("/test-{}-{}/", test_name, uuid::Uuid::new_v4());
    let config = StoreConfig {
        endpoints: vec![ETCD_ENDPOINT.to_string()],
        prefix: prefix.clone(),
    };
    let inner = EtcdStore::connect(config)
        .await
        .expect("failed to connect to etcd");
    (Arc::new(PersonhogStore::new(inner)), prefix)
}

/// Revoke the etcd lease attached to `key`, simulating a component whose
/// lease expired (etcd partition, missed heartbeats) while the process
/// itself is still running.
pub async fn revoke_lease_of_key(key: &str) {
    let mut client = etcd_client::Client::connect([ETCD_ENDPOINT], None)
        .await
        .expect("connect raw etcd client");
    let resp = client.get(key, None).await.expect("get key");
    let kv = resp
        .kvs()
        .first()
        .unwrap_or_else(|| panic!("key {key} not found"));
    let lease_id = kv.lease();
    assert_ne!(lease_id, 0, "key {key} has no lease attached");
    client.lease_revoke(lease_id).await.expect("revoke lease");
}

pub async fn wait_for_condition<F, Fut>(timeout: Duration, interval: Duration, f: F)
where
    F: Fn() -> Fut,
    Fut: Future<Output = bool>,
{
    let start = Instant::now();
    while start.elapsed() < timeout {
        if f().await {
            return;
        }
        tokio::time::sleep(interval).await;
    }
    panic!("condition not met within {timeout:?}");
}

/// `wait_for_condition` with a description of what is being waited on.
///
/// A bare timeout reports "condition not met", which names nothing —
/// and for tests whose whole assertion *is* the wait, that is the entire
/// failure message. Worth using wherever the timeout is the assertion
/// rather than a setup step. (`#[track_caller]` would be the zero-churn
/// answer, but it is a no-op on async fns.)
#[allow(dead_code)]
pub async fn wait_for_condition_named<F, Fut>(
    timeout: Duration,
    interval: Duration,
    what: &str,
    f: F,
) where
    F: Fn() -> Fut,
    Fut: Future<Output = bool>,
{
    let start = Instant::now();
    while start.elapsed() < timeout {
        if f().await {
            return;
        }
        tokio::time::sleep(interval).await;
    }
    panic!("timed out after {timeout:?} waiting for {what}");
}

// ── Component builders ──────────────────────────────────────────

pub fn start_coordinator(
    store: Arc<PersonhogStore>,
    strategy: Arc<dyn AssignmentStrategy>,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    start_coordinator_named(store, "coordinator-0", 10, strategy, cancel)
}

pub fn start_coordinator_named(
    store: Arc<PersonhogStore>,
    name: &str,
    leader_lease_ttl: i64,
    strategy: Arc<dyn AssignmentStrategy>,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    start_coordinator_with_deadline(
        store,
        name,
        leader_lease_ttl,
        Duration::from_secs(86_400),
        strategy,
        cancel,
    )
}

pub fn start_coordinator_with_deadline(
    store: Arc<PersonhogStore>,
    name: &str,
    leader_lease_ttl: i64,
    handoff_deadline: Duration,
    strategy: Arc<dyn AssignmentStrategy>,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    let keepalive_secs = (leader_lease_ttl as u64 / 3).max(1);
    let coordinator = Coordinator::new(
        store,
        CoordinatorConfig {
            name: name.to_string(),
            leader_lease_ttl,
            keepalive_interval: Duration::from_secs(keepalive_secs),
            // Short enough that a failover never waits on the leader-key
            // watch alone.
            standby_poll_interval: Duration::from_millis(500),
            run_retry_backoff: Duration::from_millis(10),
            backoff_decay_window: Duration::from_secs(300),
            rebalance_debounce_interval: Duration::from_millis(100),
            reconcile_interval: Duration::from_millis(500),
            // Callers default this to a day: these tests deliberately
            // park handoffs mid-phase to assert what the protocol does
            // with them, and a live deadline would replace the state
            // under test. The cancellation test passes a short one
            // explicitly.
            handoff_deadline,
            warming_deadline: Duration::from_secs(86_400),
        },
        strategy,
        None,
    );
    let token = cancel.child_token();
    tokio::spawn(async move {
        coordinator.run(token).await;
        Ok(())
    })
}

pub struct PodHandles {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    pub join_handle: Option<JoinHandle<Result<()>>>,
}

pub fn start_pod(store: Arc<PersonhogStore>, name: &str, cancel: CancellationToken) -> PodHandles {
    start_pod_with_lease_ttl(store, name, 10, cancel)
}

pub fn start_pod_with_lease_ttl(
    store: Arc<PersonhogStore>,
    name: &str,
    lease_ttl: i64,
    cancel: CancellationToken,
) -> PodHandles {
    start_pod_with_address(store, name, lease_ttl, None, cancel)
}

pub fn start_pod_with_address(
    store: Arc<PersonhogStore>,
    name: &str,
    lease_ttl: i64,
    advertise_address: Option<String>,
    cancel: CancellationToken,
) -> PodHandles {
    let heartbeat_secs = (lease_ttl as u64 / 3).max(1);
    let (handler, events) = MockHandoffHandler::new();
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            lease_ttl,
            heartbeat_interval: Duration::from_secs(heartbeat_secs),
            advertise_address,
            // Parked: event-driven tests assert exact handler-call
            // sequences a live reconcile pass would duplicate.
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    PodHandles {
        events,
        join_handle: Some(join_handle),
    }
}

/// A handler whose `resume_partition` fails a fixed number of times
/// before succeeding — the shape of a resume that has to take broker
/// state and hits a transient error.
pub struct FlakyResumeHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    remaining_failures: AtomicUsize,
}

#[async_trait]
impl HandoffHandler for FlakyResumeHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        if self.remaining_failures.load(Ordering::SeqCst) > 0 {
            self.remaining_failures.fetch_sub(1, Ordering::SeqCst);
            return Err(personhog_coordination::error::Error::invalid_state(
                "resume failed (test)",
            ));
        }
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

/// Start a pod whose first `failures` resume attempts fail.
pub fn start_pod_with_flaky_resume(
    store: Arc<PersonhogStore>,
    name: &str,
    failures: usize,
    cancel: CancellationToken,
) -> PodHandles {
    let events = Arc::new(Mutex::new(Vec::new()));
    let handler = FlakyResumeHandler {
        events: Arc::clone(&events),
        remaining_failures: AtomicUsize::new(failures),
    };
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
            advertise_address: None,
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    PodHandles {
        events,
        join_handle: Some(join_handle),
    }
}

/// A handler whose first `failures` release attempts fail — the shape of
/// a release that has to give back broker state and hits a transient
/// error.
pub struct FlakyReleaseHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    remaining_failures: AtomicUsize,
}

#[async_trait]
impl HandoffHandler for FlakyReleaseHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        if self.remaining_failures.load(Ordering::SeqCst) > 0 {
            self.remaining_failures.fetch_sub(1, Ordering::SeqCst);
            return Err(personhog_coordination::error::Error::invalid_state(
                "release failed (test)",
            ));
        }
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

/// Start a pod whose first `failures` release attempts fail.
pub fn start_pod_with_flaky_release(
    store: Arc<PersonhogStore>,
    name: &str,
    failures: usize,
    cancel: CancellationToken,
) -> PodHandles {
    let events = Arc::new(Mutex::new(Vec::new()));
    let handler = FlakyReleaseHandler {
        events: Arc::clone(&events),
        remaining_failures: AtomicUsize::new(failures),
    };
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
            advertise_address: None,
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    PodHandles {
        events,
        join_handle: Some(join_handle),
    }
}

/// A handler whose `drain_partition_inflight` always fails for one
/// partition — the shape of a drain that cannot quiesce whatever the
/// pod does.
pub struct StuckDrainHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    stuck: u32,
}

#[async_trait]
impl HandoffHandler for StuckDrainHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        if partition == self.stuck {
            self.events
                .lock()
                .await
                .push(HandoffEvent::DrainFailed(partition));
            return Err(personhog_coordination::error::Error::invalid_state(
                format!("drain refuses for partition {partition}"),
            ));
        }
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

/// Start a pod whose drain refuses for exactly one partition.
pub fn start_pod_with_stuck_drain(
    store: Arc<PersonhogStore>,
    name: &str,
    stuck: u32,
    lease_ttl: i64,
    cancel: CancellationToken,
) -> PodHandles {
    let events = Arc::new(Mutex::new(Vec::new()));
    let handler = StuckDrainHandler {
        events: Arc::clone(&events),
        stuck,
    };
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            lease_ttl,
            heartbeat_interval: Duration::from_secs((lease_ttl / 5).max(1) as u64),
            advertise_address: None,
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    PodHandles {
        events,
        join_handle: Some(join_handle),
    }
}

/// A handler whose `drain_partition_inflight` hangs forever for one
/// partition — the shape of in-flight work that never quiesces, which
/// only the self-fence's own timeout can end.
pub struct HangingDrainHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    hung: u32,
}

#[async_trait]
impl HandoffHandler for HangingDrainHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        if partition == self.hung {
            pending::<()>().await;
        }
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

/// Start a pod whose drain hangs forever for exactly one partition.
pub fn start_pod_with_hanging_drain(
    store: Arc<PersonhogStore>,
    name: &str,
    hung: u32,
    lease_ttl: i64,
    cancel: CancellationToken,
) -> PodHandles {
    let events = Arc::new(Mutex::new(Vec::new()));
    let handler = HangingDrainHandler {
        events: Arc::clone(&events),
        hung,
    };
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            lease_ttl,
            heartbeat_interval: Duration::from_secs((lease_ttl / 5).max(1) as u64),
            advertise_address: None,
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    PodHandles {
        events,
        join_handle: Some(join_handle),
    }
}

/// A handler whose `release_partition` always fails, recording every
/// partition it was asked to give up before it does.
///
/// Failing for *every* partition is what makes the attempt log
/// order-independent: the release loop walks a `HashSet`, so a handler
/// that failed for only one would prove nothing when that one happened to
/// be walked last.
pub struct FailingReleaseHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    attempts: Arc<Mutex<Vec<u32>>>,
}

#[async_trait]
impl HandoffHandler for FailingReleaseHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.attempts.lock().await.push(partition);
        Err(personhog_coordination::error::Error::invalid_state(
            format!("release refuses for partition {partition}"),
        ))
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

/// Start a pod whose every release fails, alongside the log of which
/// partitions it was asked to release.
pub fn start_pod_with_failing_release(
    store: Arc<PersonhogStore>,
    name: &str,
    lease_ttl: i64,
    cancel: CancellationToken,
) -> (PodHandles, Arc<Mutex<Vec<u32>>>) {
    let events = Arc::new(Mutex::new(Vec::new()));
    let attempts = Arc::new(Mutex::new(Vec::new()));
    let handler = FailingReleaseHandler {
        events: Arc::clone(&events),
        attempts: Arc::clone(&attempts),
    };
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            lease_ttl,
            heartbeat_interval: Duration::from_secs((lease_ttl / 5).max(1) as u64),
            advertise_address: None,
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    (
        PodHandles {
            events,
            join_handle: Some(join_handle),
        },
        attempts,
    )
}

/// Start a pod whose warm_partition blocks forever. Useful for testing
/// crashes during the Warming phase.
pub fn start_pod_blocking(
    store: Arc<PersonhogStore>,
    name: &str,
    lease_ttl: i64,
    cancel: CancellationToken,
) -> PodHandles {
    let heartbeat_secs = (lease_ttl as u64 / 3).max(1);
    let (handler, events) = BlockingHandoffHandler::new();
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            lease_ttl,
            heartbeat_interval: Duration::from_secs(heartbeat_secs),
            // Parked: event-driven tests assert exact handler-call
            // sequences a live reconcile pass would duplicate.
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    PodHandles {
        events,
        join_handle: Some(join_handle),
    }
}

/// Coordinator whose reconcile tick and phase deadlines are parked, so a
/// test can prove an advancement was event-driven rather than rescued by
/// the periodic backstop.
pub fn start_coordinator_reconcile_parked(
    store: Arc<PersonhogStore>,
    strategy: Arc<dyn AssignmentStrategy>,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    let coordinator = Coordinator::new(
        store,
        CoordinatorConfig {
            reconcile_interval: Duration::from_secs(86_400),
            handoff_deadline: Duration::from_secs(86_400),
            warming_deadline: Duration::from_secs(86_400),
            ..Default::default()
        },
        strategy,
        None,
    );
    let token = cancel.child_token();
    tokio::spawn(async move {
        coordinator.run(token).await;
        Ok(())
    })
}

pub fn start_coordinator_with_debounce(
    store: Arc<PersonhogStore>,
    strategy: Arc<dyn AssignmentStrategy>,
    debounce_interval: Duration,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    let coordinator = Coordinator::new(
        store,
        CoordinatorConfig {
            rebalance_debounce_interval: debounce_interval,
            ..Default::default()
        },
        strategy,
        None,
    );
    let token = cancel.child_token();
    tokio::spawn(async move {
        coordinator.run(token).await;
        Ok(())
    })
}

pub fn start_pod_slow(
    store: Arc<PersonhogStore>,
    name: &str,
    warm_delay: Duration,
    cancel: CancellationToken,
) -> PodHandles {
    let (handler, events) = SlowHandoffHandler::new(warm_delay);
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            // Parked: event-driven tests assert exact handler-call
            // sequences a live reconcile pass would duplicate.
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    PodHandles {
        events,
        join_handle: Some(join_handle),
    }
}

pub struct RouterHandles {
    pub events: Arc<Mutex<Vec<CutoverEvent>>>,
    pub addresses: Arc<StdRwLock<HashMap<String, String>>>,
    pub table: Arc<RwLock<HashMap<u32, String>>>,
    pub join_handle: Option<JoinHandle<Result<()>>>,
}

pub fn start_router(
    store: Arc<PersonhogStore>,
    name: &str,
    cancel: CancellationToken,
) -> RouterHandles {
    start_router_with_lease_ttl(store, name, 10, cancel)
}

pub fn start_router_with_lease_ttl(
    store: Arc<PersonhogStore>,
    name: &str,
    lease_ttl: i64,
    cancel: CancellationToken,
) -> RouterHandles {
    let heartbeat_secs = (lease_ttl as u64 / 3).max(1);
    let (handler, events) = MockCutoverHandler::new();
    let router = RoutingTable::new(
        store,
        RoutingTableConfig {
            router_name: name.to_string(),
            lease_ttl,
            heartbeat_interval: Duration::from_secs(heartbeat_secs),
            // Parked: event-driven tests assert exact handler-call
            // sequences, which a live reconcile pass would re-assert
            // nondeterministically. Reconcile-specific tests pass a
            // short interval explicitly.
            reconcile_interval: Duration::from_secs(86_400),
            ..RoutingTableConfig::default()
        },
    );
    let table = router.table_handle();
    let addresses = router.addresses_handle();
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { router.run(token, Arc::new(handler)).await });
    RouterHandles {
        events,
        addresses,
        table,
        join_handle: Some(join_handle),
    }
}

/// Connect a store to an arbitrary endpoint (e.g. a `FlakyProxy`) under
/// an explicit prefix, so a component under test can run through a
/// fault-injected connection while the test asserts against a direct one.
pub async fn store_at(endpoint: &str, prefix: &str) -> Arc<PersonhogStore> {
    let config = StoreConfig {
        endpoints: vec![endpoint.to_string()],
        prefix: prefix.to_string(),
    };
    let inner = EtcdStore::connect(config)
        .await
        .expect("failed to connect store");
    Arc::new(PersonhogStore::new(inner))
}

/// A byte-forwarding TCP proxy for fault-injecting a component's etcd
/// connection: `sever` breaks every live connection (in-flight streams
/// error; reconnects still succeed), `set_blackholed(true)` also kills
/// new connections on accept, so recovery is impossible until it is
/// lifted, and `set_hanging(true)` accepts them and then does nothing.
///
/// The three are different failures, and the difference matters. Severed
/// and blackholed both fail *fast* — the client gets a reset and an error
/// it can act on. Hanging is the silent partition: the connection is
/// established, the request goes out, and no answer ever comes, so a
/// caller with no timeout of its own waits for the transport rather than
/// for anything it chose.
pub struct FlakyProxy {
    /// Endpoint URL to hand to `store_at`.
    pub endpoint: String,
    conns: Arc<StdMutex<Vec<tokio::task::JoinHandle<()>>>>,
    /// Accepted-and-parked sockets, held open so the peer sees a live
    /// connection that never answers. Dropping them would turn the hang
    /// into a reset, which is the failure this mode exists to not be.
    parked: Arc<StdMutex<Vec<TcpStream>>>,
    blackholed: Arc<AtomicBool>,
    hanging: Arc<AtomicBool>,
    accepted: Arc<AtomicUsize>,
    listener: tokio::task::JoinHandle<()>,
}

impl FlakyProxy {
    pub async fn start(upstream: &'static str) -> Self {
        let socket = TcpListener::bind("127.0.0.1:0").await.expect("bind proxy");
        let endpoint = format!("http://{}", socket.local_addr().expect("proxy addr"));
        let conns: Arc<StdMutex<Vec<tokio::task::JoinHandle<()>>>> =
            Arc::new(StdMutex::new(Vec::new()));
        let parked: Arc<StdMutex<Vec<TcpStream>>> = Arc::new(StdMutex::new(Vec::new()));
        let blackholed = Arc::new(AtomicBool::new(false));
        let hanging = Arc::new(AtomicBool::new(false));
        let accepted = Arc::new(AtomicUsize::new(0));
        let accepted_bg = Arc::clone(&accepted);
        let conns_bg = Arc::clone(&conns);
        let parked_bg = Arc::clone(&parked);
        let blackholed_bg = Arc::clone(&blackholed);
        let hanging_bg = Arc::clone(&hanging);
        let listener = tokio::spawn(async move {
            loop {
                let Ok((mut client, _)) = socket.accept().await else {
                    return;
                };
                accepted_bg.fetch_add(1, Ordering::SeqCst);
                if blackholed_bg.load(Ordering::SeqCst) {
                    drop(client);
                    continue;
                }
                if hanging_bg.load(Ordering::SeqCst) {
                    // Held rather than dropped: the peer must see a
                    // connection that is open and silent, not one that
                    // was refused.
                    parked_bg.lock().unwrap().push(client);
                    continue;
                }
                let pump = tokio::spawn(async move {
                    let Ok(mut upstream_conn) = TcpStream::connect(upstream).await else {
                        return;
                    };
                    drop(copy_bidirectional(&mut client, &mut upstream_conn).await);
                });
                conns_bg.lock().unwrap().push(pump);
            }
        });
        Self {
            endpoint,
            conns,
            parked,
            blackholed,
            hanging,
            accepted,
            listener,
        }
    }

    /// How many connections the proxy has accepted since it started.
    ///
    /// A blackholed proxy drops each one immediately, so a client that
    /// keeps retrying keeps climbing this — which is what makes "it is
    /// still trying" a fact a test can wait on rather than a duration it
    /// hopes is long enough.
    pub fn accepted(&self) -> usize {
        self.accepted.load(Ordering::SeqCst)
    }

    /// Break every live connection; the streams running over them error
    /// out. New connections still succeed unless blackholed.
    pub fn sever(&self) {
        for pump in self.conns.lock().unwrap().drain(..) {
            pump.abort();
        }
    }

    pub fn set_blackholed(&self, blackholed: bool) {
        self.blackholed.store(blackholed, Ordering::SeqCst);
    }

    /// Accept new connections and then answer nothing on them.
    ///
    /// The silent partition: a caller that sets no timeout of its own
    /// waits for the transport to give up rather than for a deadline it
    /// chose, which is what makes an unraced etcd call outlast the budget
    /// its component was given.
    pub fn set_hanging(&self, hanging: bool) {
        self.hanging.store(hanging, Ordering::SeqCst);
    }
}

impl Drop for FlakyProxy {
    fn drop(&mut self) {
        self.listener.abort();
        self.sever();
        self.parked.lock().unwrap().clear();
    }
}

// ── Mock handlers ───────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HandoffEvent {
    Drained(u32),
    /// A drain attempt that returned an error — pushed by handlers whose
    /// failures are the scenario, so tests can sequence on the attempt
    /// having happened rather than racing the watch.
    DrainFailed(u32),
    Warmed(u32),
    Released(u32),
    Resumed(u32),
}

pub struct MockHandoffHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
}

impl MockHandoffHandler {
    pub fn new() -> (Self, Arc<Mutex<Vec<HandoffEvent>>>) {
        let events = Arc::new(Mutex::new(Vec::new()));
        (
            Self {
                events: Arc::clone(&events),
            },
            events,
        )
    }
}

#[async_trait]
impl HandoffHandler for MockHandoffHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

/// A handoff handler that blocks forever on warm_partition.
/// Simulates a pod that crashes before warming completes.
pub struct BlockingHandoffHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
}

impl BlockingHandoffHandler {
    pub fn new() -> (Self, Arc<Mutex<Vec<HandoffEvent>>>) {
        let events = Arc::new(Mutex::new(Vec::new()));
        (
            Self {
                events: Arc::clone(&events),
            },
            events,
        )
    }
}

#[async_trait]
impl HandoffHandler for BlockingHandoffHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, _partition: u32) -> Result<()> {
        // Block forever — simulates a slow warm that never completes
        pending().await
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

/// Per-partition gates for `GatedWarmHandler`: a warm parks until its
/// partition's gate opens, giving tests deterministic control over which
/// warms are in flight at once. A gate stays open once opened.
#[derive(Clone, Default)]
pub struct WarmGates {
    open: Arc<StdMutex<HashSet<u32>>>,
    notify: Arc<Notify>,
}

impl WarmGates {
    pub fn open(&self, partition: u32) {
        self.open.lock().unwrap().insert(partition);
        self.notify.notify_waiters();
    }

    async fn wait_open(&self, partition: u32) {
        loop {
            let notified = self.notify.notified();
            if self.open.lock().unwrap().contains(&partition) {
                return;
            }
            notified.await;
        }
    }
}

/// A handoff handler whose warms park on per-partition gates while
/// recording how many warms run concurrently — in total and for the same
/// partition. Drives the convergence-lane tests: the gates prove
/// cross-partition parallelism and the warm-slot bound, and the
/// same-partition maximum pins single-flight convergence.
pub struct GatedWarmHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    pub gates: WarmGates,
    pub warms_in_flight: Arc<StdMutex<HashMap<u32, usize>>>,
    pub max_concurrent_warms: Arc<AtomicUsize>,
    pub max_concurrent_same_partition: Arc<AtomicUsize>,
}

impl GatedWarmHandler {
    pub fn new() -> Self {
        Self {
            events: Arc::new(Mutex::new(Vec::new())),
            gates: WarmGates::default(),
            warms_in_flight: Arc::new(StdMutex::new(HashMap::new())),
            max_concurrent_warms: Arc::new(AtomicUsize::new(0)),
            max_concurrent_same_partition: Arc::new(AtomicUsize::new(0)),
        }
    }
}

#[async_trait]
impl HandoffHandler for GatedWarmHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        {
            let mut in_flight = self.warms_in_flight.lock().unwrap();
            *in_flight.entry(partition).or_insert(0) += 1;
            let total: usize = in_flight.values().sum();
            self.max_concurrent_warms.fetch_max(total, Ordering::SeqCst);
            self.max_concurrent_same_partition
                .fetch_max(in_flight[&partition], Ordering::SeqCst);
        }
        self.gates.wait_open(partition).await;
        *self
            .warms_in_flight
            .lock()
            .unwrap()
            .get_mut(&partition)
            .unwrap() -= 1;
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

pub struct GatedPodHandles {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    pub gates: WarmGates,
    pub warms_in_flight: Arc<StdMutex<HashMap<u32, usize>>>,
    pub max_concurrent_warms: Arc<AtomicUsize>,
    pub max_concurrent_same_partition: Arc<AtomicUsize>,
    pub join_handle: JoinHandle<Result<()>>,
}

/// Start a pod backed by a `GatedWarmHandler` with the given warm
/// concurrency bound.
pub fn start_pod_gated(
    store: Arc<PersonhogStore>,
    name: &str,
    warm_concurrency: usize,
    cancel: CancellationToken,
) -> GatedPodHandles {
    let handler = GatedWarmHandler::new();
    let events = Arc::clone(&handler.events);
    let gates = handler.gates.clone();
    let warms_in_flight = Arc::clone(&handler.warms_in_flight);
    let max_concurrent_warms = Arc::clone(&handler.max_concurrent_warms);
    let max_concurrent_same_partition = Arc::clone(&handler.max_concurrent_same_partition);
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            warm_concurrency,
            // Parked: event-driven tests assert exact handler-call
            // sequences a live reconcile pass would duplicate.
            reconcile_interval: Duration::from_secs(86_400),
            ..Default::default()
        },
        Arc::new(handler),
        None,
        Arc::new(AuthorityClock::unclaimed()),
    );
    let token = cancel.child_token();
    let join_handle = tokio::spawn(async move { pod.run(token).await });
    GatedPodHandles {
        events,
        gates,
        warms_in_flight,
        max_concurrent_warms,
        max_concurrent_same_partition,
        join_handle,
    }
}

/// A handoff handler that adds a configurable delay to warm_partition.
/// Simulates a pod that takes time to warm its cache.
pub struct SlowHandoffHandler {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
    pub warm_delay: Duration,
}

impl SlowHandoffHandler {
    pub fn new(warm_delay: Duration) -> (Self, Arc<Mutex<Vec<HandoffEvent>>>) {
        let events = Arc::new(Mutex::new(Vec::new()));
        (
            Self {
                events: Arc::clone(&events),
                warm_delay,
            },
            events,
        )
    }
}

#[async_trait]
impl HandoffHandler for SlowHandoffHandler {
    async fn drain_partition_inflight(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Drained(partition));
        Ok(())
    }

    async fn warm_partition(&self, partition: u32) -> Result<()> {
        tokio::time::sleep(self.warm_delay).await;
        self.events
            .lock()
            .await
            .push(HandoffEvent::Warmed(partition));
        Ok(())
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
    }

    async fn resume_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Resumed(partition));
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CutoverEvent {
    StashBegan { partition: u32, new_owner: String },
    StashDrained { partition: u32, target: String },
}

pub struct MockCutoverHandler {
    pub events: Arc<Mutex<Vec<CutoverEvent>>>,
}

impl MockCutoverHandler {
    pub fn new() -> (Self, Arc<Mutex<Vec<CutoverEvent>>>) {
        let events = Arc::new(Mutex::new(Vec::new()));
        (
            Self {
                events: Arc::clone(&events),
            },
            events,
        )
    }
}

#[async_trait]
impl StashHandler for MockCutoverHandler {
    async fn begin_stash(&self, partition: u32, new_owner: &str) -> Result<()> {
        self.events.lock().await.push(CutoverEvent::StashBegan {
            partition,
            new_owner: new_owner.to_string(),
        });
        Ok(())
    }

    async fn drain_stash(
        &self,
        partition: u32,
        target: &str,
        _cancel: CancellationToken,
    ) -> Result<()> {
        self.events.lock().await.push(CutoverEvent::StashDrained {
            partition,
            target: target.to_string(),
        });
        Ok(())
    }
}
