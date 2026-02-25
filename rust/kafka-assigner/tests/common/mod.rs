#![allow(dead_code)]

use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tokio_util::sync::CancellationToken;
use tonic::transport::Server;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use kafka_assigner::assigner::{Assigner, AssignerConfig};
use kafka_assigner::consumer_registry::ConsumerRegistry;
use kafka_assigner::error::Result;
use kafka_assigner::grpc::relay::run_relay;
use kafka_assigner::grpc::server::KafkaAssignerService;
use kafka_assigner::store::KafkaAssignerStore;
use kafka_assigner::strategy::StickyBalancedStrategy;
use kafka_assigner::types::{
    ConsumerStatus, HandoffPhase, RegisteredConsumer, TopicConfig, TopicPartition,
};
use kafka_assigner_proto::kafka_assigner::v1::kafka_assigner_client::KafkaAssignerClient;
use kafka_assigner_proto::kafka_assigner::v1::kafka_assigner_server::KafkaAssignerServer;

pub const ETCD_ENDPOINT: &str = "http://localhost:2379";
pub const WAIT_TIMEOUT: Duration = Duration::from_secs(10);
pub const POLL_INTERVAL: Duration = Duration::from_millis(100);
pub const NUM_PARTITIONS: u32 = 8;

pub async fn test_store(test_name: &str) -> Arc<KafkaAssignerStore> {
    let prefix = format!("/test-{}-{}/", test_name, uuid::Uuid::new_v4());
    let config = StoreConfig {
        endpoints: vec![ETCD_ENDPOINT.to_string()],
        prefix,
    };
    let inner = EtcdStore::connect(config)
        .await
        .expect("failed to connect to etcd");
    Arc::new(KafkaAssignerStore::new(inner))
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

pub fn start_assigner(
    store: Arc<KafkaAssignerStore>,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    start_assigner_with_config(store, AssignerConfig::default(), cancel)
}

pub fn start_assigner_with_config(
    store: Arc<KafkaAssignerStore>,
    config: AssignerConfig,
    cancel: CancellationToken,
) -> JoinHandle<Result<()>> {
    let strategy = Arc::new(StickyBalancedStrategy);
    let assigner = Assigner::new(store, config, strategy);
    let token = cancel.child_token();
    tokio::spawn(async move { assigner.run(token).await })
}

// ── Consumer simulation ─────────────────────────────────────────

pub struct ConsumerHandle {
    pub name: String,
    pub lease_id: i64,
    keepalive_task: JoinHandle<()>,
}

pub async fn register_consumer(
    store: &KafkaAssignerStore,
    name: &str,
    lease_ttl: i64,
) -> ConsumerHandle {
    let lease_id = store.grant_lease(lease_ttl).await.unwrap();
    let consumer = RegisteredConsumer {
        consumer_name: name.to_string(),
        status: ConsumerStatus::Ready,
        registered_at: assignment_coordination::util::now_seconds(),
    };
    store.register_consumer(&consumer, lease_id).await.unwrap();

    let keepalive_store = store.clone();
    let keepalive_interval = Duration::from_secs((lease_ttl as u64 / 3).max(1));
    let task = tokio::spawn(async move {
        let Ok((mut keeper, mut stream)) = keepalive_store.keep_alive(lease_id).await else {
            return;
        };
        loop {
            tokio::time::sleep(keepalive_interval).await;
            if keeper.keep_alive().await.is_err() {
                break;
            }
            if stream.message().await.ok().flatten().is_none() {
                break;
            }
        }
    });

    ConsumerHandle {
        name: name.to_string(),
        lease_id,
        keepalive_task: task,
    }
}

pub async fn kill_consumer(store: &KafkaAssignerStore, handle: ConsumerHandle) {
    handle.keepalive_task.abort();
    drop(store.revoke_lease(handle.lease_id).await);
}

// ── Handoff simulation ──────────────────────────────────────────

pub async fn signal_ready(store: &KafkaAssignerStore, tp: &TopicPartition) {
    let mut handoff = store
        .get_handoff(tp)
        .await
        .unwrap()
        .expect("handoff should exist to signal ready");
    handoff.phase = HandoffPhase::Ready;
    store.put_handoff(&handoff).await.unwrap();
}

pub async fn signal_released(store: &KafkaAssignerStore, tp: &TopicPartition) {
    store.delete_handoff(tp).await.unwrap();
}

/// Drive all in-flight handoffs to completion by simulating consumer behavior.
///
/// Polls for handoffs and advances them:
/// - Warming → signals Ready (simulates consumer finishing warm-up)
/// - Complete → signals Released (simulates consumer releasing partition)
/// - Ready → waits (assigner will transition to Complete)
///
/// Returns when no handoffs remain.
pub async fn drive_handoffs_to_completion(store: &KafkaAssignerStore) {
    let store = store.clone();
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = store.clone();
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            for h in &handoffs {
                match h.phase {
                    HandoffPhase::Warming => {
                        signal_ready(&store, &h.topic_partition()).await;
                    }
                    HandoffPhase::Complete => {
                        signal_released(&store, &h.topic_partition()).await;
                    }
                    HandoffPhase::Ready => {}
                }
            }
            handoffs.is_empty()
        }
    })
    .await;
}

// ── Config helpers ──────────────────────────────────────────────

pub async fn set_topic_config(store: &KafkaAssignerStore, topic: &str, partition_count: u32) {
    store
        .set_topic_config(&TopicConfig {
            topic: topic.to_string(),
            partition_count,
        })
        .await
        .unwrap();
}

// ── gRPC test infrastructure ────────────────────────────────────

pub struct GrpcTestServer {
    pub addr: SocketAddr,
    pub registry: Arc<ConsumerRegistry>,
    server_task: JoinHandle<()>,
    relay_task: JoinHandle<()>,
}

pub async fn start_grpc_server(
    store: Arc<KafkaAssignerStore>,
    cancel: CancellationToken,
) -> GrpcTestServer {
    let registry = Arc::new(ConsumerRegistry::new());
    let service = KafkaAssignerService::new(Arc::clone(&store), Arc::clone(&registry));

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let server_task = tokio::spawn(async move {
        Server::builder()
            .add_service(KafkaAssignerServer::new(service))
            .serve_with_incoming(TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    let relay_store = Arc::clone(&store);
    let relay_registry = Arc::clone(&registry);
    let relay_cancel = cancel.child_token();
    let relay_task = tokio::spawn(async move {
        if let Err(e) = run_relay(relay_store, relay_registry, relay_cancel).await {
            tracing::warn!(error = %e, "relay exited with error");
        }
    });

    // Brief pause for the server to start accepting connections.
    tokio::time::sleep(Duration::from_millis(50)).await;

    GrpcTestServer {
        addr,
        registry,
        server_task,
        relay_task,
    }
}

pub async fn create_grpc_client(
    addr: SocketAddr,
) -> KafkaAssignerClient<tonic::transport::Channel> {
    let url = format!("http://{addr}");
    KafkaAssignerClient::connect(url)
        .await
        .expect("failed to connect to test gRPC server")
}
