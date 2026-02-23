use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use personhog_coordination::coordinator::{Coordinator, CoordinatorConfig};
use personhog_coordination::error::Result;
use personhog_coordination::pod::{HandoffHandler, PodConfig, PodHandle};
use personhog_coordination::routing_table::{CutoverHandler, RoutingTable, RoutingTableConfig};
use personhog_coordination::store::{EtcdStore, StoreConfig};
use personhog_coordination::strategy::AssignmentStrategy;

pub const ETCD_ENDPOINT: &str = "http://localhost:2379";
pub const WAIT_TIMEOUT: Duration = Duration::from_secs(10);
pub const POLL_INTERVAL: Duration = Duration::from_millis(100);

pub async fn test_store(test_name: &str) -> Arc<EtcdStore> {
    let prefix = format!("/test-{}-{}/", test_name, uuid::Uuid::new_v4());
    let config = StoreConfig {
        endpoints: vec![ETCD_ENDPOINT.to_string()],
        prefix,
    };
    Arc::new(
        EtcdStore::connect(config)
            .await
            .expect("failed to connect to etcd"),
    )
}

pub async fn wait_for_condition<F, Fut>(timeout: Duration, interval: Duration, f: F)
where
    F: Fn() -> Fut,
    Fut: Future<Output = bool>,
{
    let start = std::time::Instant::now();
    while start.elapsed() < timeout {
        if f().await {
            return;
        }
        tokio::time::sleep(interval).await;
    }
    panic!("condition not met within {timeout:?}");
}

// ── Component builders ──────────────────────────────────────────

pub fn start_coordinator(
    store: Arc<EtcdStore>,
    strategy: Arc<dyn AssignmentStrategy>,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    start_coordinator_named(store, "coordinator-0", 10, strategy, cancel)
}

pub fn start_coordinator_named(
    store: Arc<EtcdStore>,
    name: &str,
    leader_lease_ttl: i64,
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
            election_retry_interval: Duration::from_secs(1),
            rebalance_debounce_interval: Duration::from_millis(100),
        },
        strategy,
    );
    let token = cancel.child_token();
    tokio::spawn(async move { coordinator.run(token).await })
}

pub struct PodHandles {
    pub events: Arc<Mutex<Vec<HandoffEvent>>>,
}

pub fn start_pod(store: Arc<EtcdStore>, name: &str, cancel: CancellationToken) -> PodHandles {
    start_pod_with_lease_ttl(store, name, 10, cancel)
}

pub fn start_pod_with_lease_ttl(
    store: Arc<EtcdStore>,
    name: &str,
    lease_ttl: i64,
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
            ..Default::default()
        },
        Arc::new(handler),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });
    PodHandles { events }
}

/// Start a pod whose warm_partition blocks forever. Useful for testing
/// crashes during the Warming phase.
pub fn start_pod_blocking(
    store: Arc<EtcdStore>,
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
            ..Default::default()
        },
        Arc::new(handler),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });
    PodHandles { events }
}

pub fn start_coordinator_with_debounce(
    store: Arc<EtcdStore>,
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
    );
    let token = cancel.child_token();
    tokio::spawn(async move { coordinator.run(token).await })
}

pub fn start_pod_slow(
    store: Arc<EtcdStore>,
    name: &str,
    warm_delay: Duration,
    cancel: CancellationToken,
) -> PodHandles {
    let (handler, events) = SlowHandoffHandler::new(warm_delay);
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            ..Default::default()
        },
        Arc::new(handler),
    );
    let token = cancel.child_token();
    tokio::spawn(async move { pod.run(token).await });
    PodHandles { events }
}

pub struct RouterHandles {
    pub events: Arc<Mutex<Vec<CutoverEvent>>>,
    pub table: Arc<tokio::sync::RwLock<std::collections::HashMap<u32, String>>>,
}

pub fn start_router(store: Arc<EtcdStore>, name: &str, cancel: CancellationToken) -> RouterHandles {
    let (handler, events) = MockCutoverHandler::new();
    let router = RoutingTable::new(
        store,
        RoutingTableConfig {
            router_name: name.to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
        },
        Arc::new(handler),
    );
    let table = router.table_handle();
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token).await });
    RouterHandles { events, table }
}

// ── Mock handlers ───────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HandoffEvent {
    Warmed(u32),
    Released(u32),
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
    async fn warm_partition(&self, _partition: u32) -> Result<()> {
        // Block forever — simulates a slow warm that never completes
        std::future::pending().await
    }

    async fn release_partition(&self, partition: u32) -> Result<()> {
        self.events
            .lock()
            .await
            .push(HandoffEvent::Released(partition));
        Ok(())
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
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CutoverEvent {
    pub partition: u32,
    pub old_owner: String,
    pub new_owner: String,
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
impl CutoverHandler for MockCutoverHandler {
    async fn execute_cutover(
        &self,
        partition: u32,
        old_owner: &str,
        new_owner: &str,
    ) -> Result<()> {
        self.events.lock().await.push(CutoverEvent {
            partition,
            old_owner: old_owner.to_string(),
            new_owner: new_owner.to_string(),
        });
        Ok(())
    }
}
