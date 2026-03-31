use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use personhog_coordination::coordinator::{Coordinator, CoordinatorConfig};
use personhog_coordination::error::Result;
use personhog_coordination::pod::{PodConfig, PodHandle};
use personhog_coordination::routing_table::{CutoverHandler, RoutingTable, RoutingTableConfig};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::strategy::AssignmentStrategy;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use personhog_leader::cache::{CachedPerson, PartitionedCache, PersonCacheKey};
use personhog_leader::coordination::LeaderHandoffHandler;
use personhog_leader::service::PersonHogLeaderService;
use personhog_proto::personhog::leader::v1::person_hog_leader_client::PersonHogLeaderClient;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use tokio::net::TcpListener;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tonic::transport::{Channel, Server};

pub const ETCD_ENDPOINT: &str = "http://localhost:2379";
pub const WAIT_TIMEOUT: Duration = Duration::from_secs(10);
pub const POLL_INTERVAL: Duration = Duration::from_millis(100);
pub const NUM_PARTITIONS: u32 = 4;

pub async fn test_store(test_name: &str) -> Arc<PersonhogStore> {
    let prefix = format!("/test-{}-{}/", test_name, uuid::Uuid::new_v4());
    let config = StoreConfig {
        endpoints: vec![ETCD_ENDPOINT.to_string()],
        prefix,
    };
    let inner = EtcdStore::connect(config)
        .await
        .expect("failed to connect to etcd");
    Arc::new(PersonhogStore::new(inner))
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

// ── Coordinator ─────────────────────────────────────────────

pub fn start_coordinator(
    store: Arc<PersonhogStore>,
    strategy: Arc<dyn AssignmentStrategy>,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    let coordinator = Coordinator::new(
        store,
        CoordinatorConfig {
            name: "coordinator-0".to_string(),
            leader_lease_ttl: 10,
            keepalive_interval: Duration::from_secs(3),
            election_retry_interval: Duration::from_secs(1),
            rebalance_debounce_interval: Duration::from_millis(100),
        },
        strategy,
    );
    let token = cancel.child_token();
    tokio::spawn(async move { coordinator.run(token).await })
}

// ── Router (for ack quorum) ─────────────────────────────────

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

pub fn start_router(
    store: Arc<PersonhogStore>,
    name: &str,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    let (handler, _events) = MockCutoverHandler::new();
    let router = RoutingTable::new(
        store,
        RoutingTableConfig {
            router_name: name.to_string(),
            lease_ttl: 10,
            heartbeat_interval: Duration::from_secs(3),
        },
    );
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token, Arc::new(handler)).await })
}

// ── Leader pod ──────────────────────────────────────────────

pub struct LeaderPodHandles {
    pub cache: Arc<PartitionedCache>,
    pub leader_addr: SocketAddr,
}

/// Start a leader pod with real `LeaderHandoffHandler` + `PersonHogLeaderService`
/// sharing the same `PartitionedCache`. Returns handles for test assertions.
pub async fn start_leader_pod(
    store: Arc<PersonhogStore>,
    name: &str,
    cache_capacity: usize,
    cancel: CancellationToken,
) -> LeaderPodHandles {
    let cache = Arc::new(PartitionedCache::new(cache_capacity));

    // Pod with real handoff handler
    let handler = LeaderHandoffHandler::new(Arc::clone(&cache));
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: name.to_string(),
            ..Default::default()
        },
        Arc::new(handler),
    );
    let pod_token = cancel.child_token();
    tokio::spawn(async move { pod.run(pod_token).await });

    // gRPC leader service sharing the same cache
    let service = PersonHogLeaderService::new(Arc::clone(&cache));
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let leader_addr = listener.local_addr().unwrap();

    let grpc_token = cancel.child_token();
    tokio::spawn(async move {
        Server::builder()
            .add_service(PersonHogLeaderServer::new(service))
            .serve_with_incoming_shutdown(
                tokio_stream::wrappers::TcpListenerStream::new(listener),
                grpc_token.cancelled(),
            )
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;

    LeaderPodHandles { cache, leader_addr }
}

pub async fn start_leader_pod_with_lease_ttl(
    store: Arc<PersonhogStore>,
    name: &str,
    cache_capacity: usize,
    lease_ttl: i64,
    cancel: CancellationToken,
) -> LeaderPodHandles {
    let cache = Arc::new(PartitionedCache::new(cache_capacity));

    let heartbeat_secs = (lease_ttl as u64 / 3).max(1);
    let handler = LeaderHandoffHandler::new(Arc::clone(&cache));
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
    let pod_token = cancel.child_token();
    tokio::spawn(async move { pod.run(pod_token).await });

    let service = PersonHogLeaderService::new(Arc::clone(&cache));
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let leader_addr = listener.local_addr().unwrap();

    let grpc_token = cancel.child_token();
    tokio::spawn(async move {
        Server::builder()
            .add_service(PersonHogLeaderServer::new(service))
            .serve_with_incoming_shutdown(
                tokio_stream::wrappers::TcpListenerStream::new(listener),
                grpc_token.cancelled(),
            )
            .await
            .unwrap();
    });

    tokio::time::sleep(Duration::from_millis(10)).await;

    LeaderPodHandles { cache, leader_addr }
}

// ── Helpers ─────────────────────────────────────────────────

pub async fn create_leader_client(addr: SocketAddr) -> PersonHogLeaderClient<Channel> {
    let url = format!("http://{}", addr);
    PersonHogLeaderClient::connect(url).await.unwrap()
}

pub fn seed_person(cache: &PartitionedCache, partition: u32, person: CachedPerson) {
    let key = PersonCacheKey {
        team_id: person.team_id,
        person_id: person.id,
    };
    cache.put(partition, key, person);
}

pub fn test_cached_person() -> CachedPerson {
    CachedPerson {
        id: 42,
        uuid: "00000000-0000-0000-0000-000000000042".to_string(),
        team_id: 1,
        properties: serde_json::json!({"email": "test@example.com"}),
        created_at: 1700000000,
        version: 1,
        is_identified: false,
    }
}
