// Each `tests/*.rs` integration test compiles as its own binary and imports
// `common` via `mod common;`. Helpers used by some test files but not others
// would otherwise fire `dead_code` per-binary; suppress at the module level.
#![allow(dead_code)]

use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;

use async_trait::async_trait;
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::{create_kafka_producer, KafkaContext};
use health::HealthRegistry;
use personhog_coordination::authority::AuthorityClock;
use personhog_coordination::coordinator::{Coordinator, CoordinatorConfig};
use personhog_coordination::error::Result;
use personhog_coordination::pod::{PodConfig, PodHandle};
use personhog_coordination::routing_table::{RoutingTable, RoutingTableConfig, StashHandler};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::strategy::AssignmentStrategy;
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{DefaultProducerContext, FutureProducer};

use assignment_coordination::store::{EtcdStore, StoreConfig};
use personhog_common::partitioning::partition_for_person;
use personhog_leader::cache::{
    approx_person_bytes, CachedPerson, DirtyIndex, PartitionedCache, PersonCacheKey,
};
use personhog_leader::coordination::LeaderHandoffHandler;
use personhog_leader::inflight::InflightTracker;
use personhog_leader::pg::PgFallback;
use personhog_leader::recovery::{ChangelogRecovery, RecoveryConfig};
use personhog_leader::service::{PersonHogLeaderService, PropertySizeLimits};
use personhog_leader::warming::WarmClientPools;
use personhog_leader::warnings::WarningsProducer;
use personhog_proto::personhog::leader::v1::person_hog_leader_client::PersonHogLeaderClient;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use tokio::net::TcpListener;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tonic::transport::{Channel, Server};

pub const ETCD_ENDPOINT: &str = "http://localhost:2379";
pub const KAFKA_BOOTSTRAP: &str = "localhost:9092";
pub const PERSONS_DB_URL: &str = "postgres://posthog:posthog@localhost:5432/posthog_persons";
pub const WAIT_TIMEOUT: Duration = Duration::from_secs(10);
pub const POLL_INTERVAL: Duration = Duration::from_millis(100);
pub const NUM_PARTITIONS: u32 = 4;

/// Find a person_id whose key hashes to `partition`, so a test can aim a
/// request at a specific partition while satisfying the leader's partition
/// validation.
pub fn person_id_for_partition(team_id: i64, partition: u32) -> i64 {
    (1..)
        .find(|pid| partition_for_person(team_id, *pid, NUM_PARTITIONS) == partition)
        .expect("every partition is reachable from some person_id")
}

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
            // Short enough that a failover never waits on the leader-key
            // watch alone.
            standby_poll_interval: Duration::from_millis(500),
            run_retry_backoff: Duration::from_millis(10),
            backoff_decay_window: Duration::from_secs(300),
            rebalance_debounce_interval: Duration::from_millis(100),
            reconcile_interval: Duration::from_millis(500),
            // Effectively disabled: these tests park handoffs to assert
            // warming behavior, and a live deadline would delete the
            // state under test.
            handoff_deadline: Duration::from_secs(86_400),
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

// ── Router (for ack quorum) ─────────────────────────────────

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
            reconcile_interval: Duration::from_secs(86_400),
            ..RoutingTableConfig::default()
        },
    );
    let token = cancel.child_token();
    tokio::spawn(async move { router.run(token, Arc::new(handler)).await })
}

// ── Leader pod ──────────────────────────────────────────────

pub const CHANGELOG_TOPIC: &str = "personhog_updates";

pub struct LeaderPodHandles {
    pub cache: Arc<PartitionedCache>,
    pub leader_addr: SocketAddr,
    // Kept alive so the mock Kafka cluster stays running for the test duration
    pub _mock_cluster: MockCluster<'static, DefaultProducerContext>,
}

/// Kafka config pointing at local kafka for e2e tests. Used for both the
/// producer and the warming consumer inside `LeaderHandoffHandler`.
pub fn test_kafka_config() -> KafkaConfig {
    KafkaConfig {
        kafka_producer_linger_ms: 0,
        kafka_producer_queue_mib: 50,
        kafka_message_timeout_ms: 5000,
        kafka_compression_codec: "none".to_string(),
        kafka_hosts: KAFKA_BOOTSTRAP.to_string(),
        kafka_tls: false,
        kafka_producer_queue_messages: 1000,
        kafka_client_rack: String::new(),
        kafka_client_id: String::new(),
        kafka_producer_batch_size: None,
        kafka_producer_batch_num_messages: None,
        kafka_producer_enable_idempotence: None,
        kafka_producer_max_in_flight_requests_per_connection: None,
        kafka_producer_topic_metadata_refresh_interval_ms: None,
        kafka_producer_message_max_bytes: None,
        kafka_producer_sticky_partitioning_linger_ms: None,
        kafka_producer_partitioner: None,
        kafka_producer_acks: None,
        kafka_producer_retries: None,
    }
}

/// Default warming knobs for e2e tests — production-equivalent timeouts and
/// retry policy. `kafka_bootstrap` must match the broker the test's
/// producer is publishing to, so the warming consumer reads from the same
/// place. With a mock cluster, that's `mock_cluster.bootstrap_servers()`;
/// with real local Kafka, `KAFKA_BOOTSTRAP`.
pub fn test_warming_config(
    pod_name: &str,
    kafka_bootstrap: &str,
) -> personhog_leader::warming::WarmingConfig {
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = kafka_bootstrap.to_string();
    personhog_leader::warming::WarmingConfig {
        kafka,
        topic: CHANGELOG_TOPIC.to_string(),
        pod_name: pod_name.to_string(),
        writer_consumer_group: "personhog-writer".to_string(),
        lookback_offsets: 0,
        committed_offsets_timeout: Duration::from_secs(5),
        fetch_watermarks_timeout: Duration::from_secs(5),
        recv_timeout: Duration::from_secs(10),
        retry: personhog_leader::warming::WarmingRetryPolicy {
            max_attempts: 3,
            initial_backoff: Duration::from_millis(500),
            max_backoff: Duration::from_secs(5),
        },
    }
}

/// Recovery pointed at the given broker. A short receive timeout keeps
/// tests that exercise failed recoveries fast.
pub fn test_recovery(kafka_bootstrap: &str) -> Arc<ChangelogRecovery> {
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = kafka_bootstrap.to_string();
    Arc::new(
        ChangelogRecovery::new(RecoveryConfig {
            kafka,
            topic: CHANGELOG_TOPIC.to_string(),
            pod_name: "test-pod".to_string(),
            recv_timeout: Duration::from_secs(2),
            pool_size: 2,
        })
        .expect("build recovery pool"),
    )
}

/// Create a producer against local Kafka for e2e tests.
pub async fn create_local_kafka_producer() -> FutureProducer<KafkaContext> {
    let registry = HealthRegistry::new("test");
    let handle = registry
        .register("kafka".to_string(), Duration::from_secs(30))
        .await;
    let config = KafkaConfig {
        kafka_producer_linger_ms: 0,
        kafka_producer_queue_mib: 50,
        kafka_message_timeout_ms: 5000,
        kafka_compression_codec: "none".to_string(),
        kafka_hosts: KAFKA_BOOTSTRAP.to_string(),
        kafka_tls: false,
        kafka_producer_queue_messages: 1000,
        kafka_client_rack: String::new(),
        kafka_client_id: String::new(),
        kafka_producer_batch_size: None,
        kafka_producer_batch_num_messages: None,
        kafka_producer_enable_idempotence: None,
        kafka_producer_max_in_flight_requests_per_connection: None,
        kafka_producer_topic_metadata_refresh_interval_ms: None,
        kafka_producer_message_max_bytes: None,
        kafka_producer_sticky_partitioning_linger_ms: None,
        kafka_producer_partitioner: None,
        kafka_producer_acks: None,
        kafka_producer_retries: None,
    };
    create_kafka_producer(&config, handle)
        .await
        .expect("failed to connect to local Kafka")
}

/// Create a mock Kafka cluster and producer for tests. The mock topic is
/// pre-created with `NUM_PARTITIONS` partitions so the warming pipeline's
/// `fetch_watermarks` calls succeed for every partition the test exercises;
/// otherwise warming aborts trying to query a non-existent partition and
/// the handoff stalls.
pub async fn create_test_kafka() -> (
    MockCluster<'static, DefaultProducerContext>,
    FutureProducer<KafkaContext>,
) {
    create_test_kafka_with_partitions(NUM_PARTITIONS as i32).await
}

/// Variant of `create_test_kafka` that lets a test pin the topic to a
/// specific partition count. Use this for tests that exercise the
/// producer's partition-routing behavior — they need a topology they
/// control, not the default warming-friendly multi-partition setup.
pub async fn create_test_kafka_with_partitions(
    partitions: i32,
) -> (
    MockCluster<'static, DefaultProducerContext>,
    FutureProducer<KafkaContext>,
) {
    let (cluster, producer) = common_kafka::test::create_mock_kafka().await;
    cluster
        .create_topic(CHANGELOG_TOPIC, partitions, 1)
        .expect("failed to create mock topic");
    (cluster, producer)
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
    let (mock_cluster, kafka_producer) = create_test_kafka().await;

    // Pod with real handoff handler. Warming consumer reads from the same
    // mock broker the producer is publishing to so the topic actually
    // exists when warming queries watermarks.
    let inflight = Arc::new(InflightTracker::new());
    // One dirty index per pod, shared by handler and service exactly as
    // main.rs wires them: warming seeds the marks the service consults.
    let dirty_index = Arc::new(DirtyIndex::new(1_000_000));
    // One per pod, shared by handler and service exactly as main.rs
    // wires them: otherwise `release_partition` clears a map the
    // service never reads, and the floors survive a handoff in tests
    // while production drops them.
    let emitted_versions = Arc::new(personhog_leader::emitted::EmittedVersions::new(1_000_000));
    // Recovery must read the broker the service produces to.
    let recovery = test_recovery(&mock_cluster.bootstrap_servers());
    let warming = test_warming_config(name, &mock_cluster.bootstrap_servers());
    let pools = Arc::new(WarmClientPools::new(
        &warming.kafka,
        name,
        &warming.writer_consumer_group,
    ));
    let handler = LeaderHandoffHandler::new(
        Arc::clone(&cache),
        Arc::clone(&inflight),
        Arc::clone(&dirty_index),
        warming,
        Arc::new(dashmap::DashMap::new()),
        None,
        NUM_PARTITIONS,
        pools,
        None,
        None,
        std::sync::Arc::clone(&emitted_versions),
    );
    let authority = Arc::new(AuthorityClock::unclaimed());
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
        authority,
    );
    let pod_token = cancel.child_token();
    tokio::spawn(async move { pod.run(pod_token).await });

    // gRPC leader service sharing the same cache
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer.clone(),
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::clone(&inflight),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        recovery,
        PropertySizeLimits::new(655360, 524288),
        WarningsProducer::new(kafka_producer, "clickhouse_ingestion_warnings".to_string()),
        Arc::new(dashmap::DashMap::new()),
        None,
        // A live claim rather than none, so the lease gate on the read
        // and write paths is exercised by every test built on this
        // fixture instead of being skipped by all of them.
        Some(live_authority()),
        std::sync::Arc::clone(&emitted_versions),
    );
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

    LeaderPodHandles {
        cache,
        leader_addr,
        _mock_cluster: mock_cluster,
    }
}

pub async fn start_leader_pod_with_lease_ttl(
    store: Arc<PersonhogStore>,
    name: &str,
    cache_capacity: usize,
    lease_ttl: i64,
    cancel: CancellationToken,
) -> LeaderPodHandles {
    let cache = Arc::new(PartitionedCache::new(cache_capacity));
    let (mock_cluster, kafka_producer) = create_test_kafka().await;

    let heartbeat_secs = (lease_ttl as u64 / 3).max(1);
    let inflight = Arc::new(InflightTracker::new());
    let dirty_index = Arc::new(DirtyIndex::new(1_000_000));
    // One per pod, shared by handler and service exactly as main.rs
    // wires them: otherwise `release_partition` clears a map the
    // service never reads, and the floors survive a handoff in tests
    // while production drops them.
    let emitted_versions = Arc::new(personhog_leader::emitted::EmittedVersions::new(1_000_000));
    let recovery = test_recovery(&mock_cluster.bootstrap_servers());
    let warming = test_warming_config(name, &mock_cluster.bootstrap_servers());
    let pools = Arc::new(WarmClientPools::new(
        &warming.kafka,
        name,
        &warming.writer_consumer_group,
    ));
    let handler = LeaderHandoffHandler::new(
        Arc::clone(&cache),
        Arc::clone(&inflight),
        Arc::clone(&dirty_index),
        warming,
        Arc::new(dashmap::DashMap::new()),
        None,
        NUM_PARTITIONS,
        pools,
        None,
        None,
        std::sync::Arc::clone(&emitted_versions),
    );
    let authority = Arc::new(AuthorityClock::unclaimed());
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
        authority,
    );
    let pod_token = cancel.child_token();
    tokio::spawn(async move { pod.run(pod_token).await });

    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer.clone(),
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::clone(&inflight),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        recovery,
        PropertySizeLimits::new(655360, 524288),
        WarningsProducer::new(kafka_producer, "clickhouse_ingestion_warnings".to_string()),
        Arc::new(dashmap::DashMap::new()),
        None,
        None,
        std::sync::Arc::clone(&emitted_versions),
    );
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

    LeaderPodHandles {
        cache,
        leader_addr,
        _mock_cluster: mock_cluster,
    }
}

// ── Helpers ─────────────────────────────────────────────────

pub async fn create_leader_client(addr: SocketAddr) -> PersonHogLeaderClient<Channel> {
    let url = format!("http://{}", addr);
    PersonHogLeaderClient::connect(url).await.unwrap()
}

/// A team id no other test shares, however the tests are scheduled.
/// Random rather than counter- or clock-derived: nextest runs each test
/// in its own process, so any per-process counter or seconds-based salt
/// hands the same id to tests launched in the same second. Tests that
/// write shared Postgres state (lifecycle marks, person rows) key it by
/// team, so a unique team makes them collision-free and self-contained
/// with no cleanup ordering to get right. Stays inside the team_id
/// column's integer range.
#[allow(dead_code)]
pub fn unique_team_id() -> i64 {
    (uuid::Uuid::new_v4().as_u128() % 900_000_000 + 100_000_000) as i64
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
        properties: serde_json::to_vec(&serde_json::json!({"email": "test@example.com"})).unwrap(),
        created_at: 1700000000,
        version: 1,
        is_identified: false,
        is_deleted: false,
        last_seen_at: None,
        approx_bytes: approx_person_bytes(64),
    }
}

/// Create a PG pool for the local persons database.
pub async fn create_persons_pool() -> sqlx::postgres::PgPool {
    sqlx::postgres::PgPool::connect(PERSONS_DB_URL)
        .await
        .expect("failed to connect to persons DB")
}

/// Start a leader service with PG fallback enabled (no etcd coordination).
/// Returns the gRPC address and the shared cache for assertions.
pub async fn start_leader_with_pg_fallback(
    cancel: CancellationToken,
) -> (
    SocketAddr,
    Arc<PartitionedCache>,
    MockCluster<'static, DefaultProducerContext>,
) {
    let cache = Arc::new(PartitionedCache::new(1 << 20));
    let (mock_cluster, kafka_producer) = create_test_kafka().await;
    let pool = create_persons_pool().await;

    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer.clone(),
        CHANGELOG_TOPIC.to_string(),
        Some(PgFallback {
            pool,
            table: "posthog_person".to_string(),
        }),
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(&mock_cluster.bootstrap_servers()),
        PropertySizeLimits::new(655360, 524288),
        WarningsProducer::new(kafka_producer, "clickhouse_ingestion_warnings".to_string()),
        Arc::new(dashmap::DashMap::new()),
        None,
        None,
        std::sync::Arc::new(personhog_leader::emitted::EmittedVersions::new(1_000_000)),
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let token = cancel.child_token();

    tokio::spawn(async move {
        Server::builder()
            .add_service(PersonHogLeaderServer::new(service))
            .serve_with_incoming_shutdown(
                tokio_stream::wrappers::TcpListenerStream::new(listener),
                token.cancelled(),
            )
            .await
            .unwrap();
    });
    tokio::time::sleep(Duration::from_millis(10)).await;

    (addr, cache, mock_cluster)
}

/// Comfortably above the test config's `message.timeout.ms`, which
/// librdkafka requires the broker bound to cover.
pub const BROKER_TXN_TIMEOUT: Duration = Duration::from_secs(30);

/// Fenced producers pointed at the local broker.
///
/// Lives here rather than beside the fencing tests because the *service*
/// needs it too: without a way to build `PersonHogLeaderService` with
/// fencing on, its entire fenced write arm — the version settlement, the
/// cache eviction, the four-way error mapping — is unreachable from any
/// test.
pub fn fenced_producers_for(topic: &str) -> personhog_leader::fencing::FencedChangelogProducers {
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = KAFKA_BOOTSTRAP.to_string();
    personhog_leader::fencing::FencedChangelogProducers::new(
        personhog_leader::fencing::FencedProducerConfig {
            kafka,
            topic: topic.to_string(),
            init_timeout: Duration::from_secs(10),
            commit_timeout: Duration::from_secs(10),
            broker_txn_timeout: BROKER_TXN_TIMEOUT,
            window: Duration::from_millis(5),
            window_max_writes: 32,
            settle_budget: Duration::from_secs(5),
        },
    )
}

/// A handoff handler wired to real fenced producers, in the shape
/// production runs: fencing on, and a lease whose renewals are current.
///
/// Deliberately not `None` for the authority. A fixture that leaves a
/// mechanism out makes every test written against it exercise the
/// degenerate path, and the gate stops being covered by anything —
/// which is exactly how all four of its call sites became deletable
/// with the suite green. Tests that need a lapsed claim pass their own.
#[allow(dead_code)]
pub fn test_handoff_handler(
    topic: &str,
    fenced: Arc<personhog_leader::fencing::FencedChangelogProducers>,
) -> personhog_leader::coordination::LeaderHandoffHandler {
    handoff_handler_with(
        topic,
        fenced,
        Arc::new(personhog_leader::inflight::InflightTracker::new()),
        live_authority(),
    )
}

/// The same handler, holding an authority clock the caller controls.
///
/// Acquisition is gated on the published claim, so every branch that
/// declines to take the epoch is unreachable while the handler carries no
/// clock at all.
#[allow(dead_code)]
pub fn test_handoff_handler_with_authority(
    topic: &str,
    fenced: Arc<personhog_leader::fencing::FencedChangelogProducers>,
    authority: Arc<AuthorityClock>,
) -> personhog_leader::coordination::LeaderHandoffHandler {
    handoff_handler_with(
        topic,
        fenced,
        Arc::new(personhog_leader::inflight::InflightTracker::new()),
        authority,
    )
}

/// The same handler, sharing its inflight tracker with the caller — the
/// only way to observe when the drain closes admissions relative to when
/// it waits.
#[allow(dead_code)]
pub fn test_handoff_handler_with_inflight(
    topic: &str,
    fenced: Arc<personhog_leader::fencing::FencedChangelogProducers>,
    inflight: Arc<personhog_leader::inflight::InflightTracker>,
) -> personhog_leader::coordination::LeaderHandoffHandler {
    handoff_handler_with(topic, fenced, inflight, live_authority())
}

/// Takes the authority clock by value rather than as an `Option`.
///
/// A fixture that can be built without one produces tests that exercise
/// the ungated path by default, and the gate stops being covered by
/// anything — which is how all four of its call sites became deletable
/// with the suite green. Requiring it makes that configuration
/// unbuildable rather than merely discouraged.
fn handoff_handler_with(
    topic: &str,
    fenced: Arc<personhog_leader::fencing::FencedChangelogProducers>,
    inflight: Arc<personhog_leader::inflight::InflightTracker>,
    authority: Arc<AuthorityClock>,
) -> personhog_leader::coordination::LeaderHandoffHandler {
    let mut warming = test_warming_config("test", KAFKA_BOOTSTRAP);
    warming.topic = topic.to_string();
    personhog_leader::coordination::LeaderHandoffHandler::new(
        Arc::new(PartitionedCache::new(1 << 20)),
        inflight,
        Arc::new(DirtyIndex::new(1_000_000)),
        warming,
        Arc::new(dashmap::DashMap::new()),
        None,
        NUM_PARTITIONS,
        Arc::new(personhog_leader::warming::WarmClientPools::new(
            &test_kafka_config(),
            "test",
            "personhog-writer",
        )),
        Some(fenced),
        Some(authority),
        Arc::new(personhog_leader::emitted::EmittedVersions::new(1_000_000)),
    )
}

/// A clock holding a claim its keepalive is still confirming.
#[allow(dead_code)]
/// A claim that stays valid for the whole of any test.
///
/// The TTL is deliberately far longer than production's. Validity lapses
/// once no renewal has been confirmed for two thirds of the TTL, and
/// nothing renews this one — so a production-shaped 30s TTL gives a 20s
/// margin, which the fencing suite's longest tests already reach. Tests
/// that want a lapsed claim surrender explicitly rather than waiting one
/// out.
pub fn live_authority() -> Arc<AuthorityClock> {
    let clock = Arc::new(AuthorityClock::unclaimed());
    clock.begin_session(Duration::from_secs(3600), std::time::Instant::now());
    clock
}
