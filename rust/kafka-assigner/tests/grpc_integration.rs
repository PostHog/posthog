mod common;

use std::collections::{BTreeMap, HashMap, HashSet};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use common::{
    create_grpc_client, set_topic_config, start_assigner, start_grpc_server, test_store,
    wait_for_condition, NUM_PARTITIONS, POLL_INTERVAL, WAIT_TIMEOUT,
};
use kafka_assigner::types::HandoffPhase;
use kafka_assigner_proto::kafka_assigner::v1 as proto;
use kafka_assigner_proto::kafka_assigner::v1::kafka_assigner_client::KafkaAssignerClient;
use proto::assignment_command::Command;
use tonic::transport::Channel;
use tonic::Streaming;

// ── Simulated deduplicator consumer ─────────────────────────────

struct SimulatedConsumer {
    name: String,
    client: KafkaAssignerClient<Channel>,
    stream: Streaming<proto::AssignmentCommand>,
    owned: HashSet<(String, u32)>,
}

impl SimulatedConsumer {
    async fn connect(addr: SocketAddr, name: &str) -> Self {
        let mut client = create_grpc_client(addr).await;
        let response = client
            .register(proto::RegisterRequest {
                consumer_name: name.to_string(),
            })
            .await
            .expect("register RPC failed");
        let stream = response.into_inner();

        Self {
            name: name.to_string(),
            client,
            stream,
            owned: HashSet::new(),
        }
    }

    async fn next_command(&mut self) -> Option<Command> {
        let msg = self.stream.message().await.ok()??;
        msg.command
    }

    fn apply_assignment(&mut self, update: &proto::AssignmentUpdate) {
        for tp in &update.assigned {
            self.owned.insert((tp.topic.clone(), tp.partition));
        }
        for tp in &update.unassigned {
            self.owned.remove(&(tp.topic.clone(), tp.partition));
        }
    }

    async fn handle_warm(&mut self, warm: &proto::WarmPartition, download_delay: Duration) {
        tokio::time::sleep(download_delay).await;

        let partition = warm.partition.as_ref().unwrap();
        self.client
            .partition_ready(proto::PartitionReadyRequest {
                consumer_name: self.name.clone(),
                partition: Some(partition.clone()),
            })
            .await
            .expect("partition_ready RPC failed");
    }

    async fn handle_release(&mut self, release: &proto::ReleasePartition) {
        let partition = release.partition.as_ref().unwrap();
        self.owned
            .remove(&(partition.topic.clone(), partition.partition));

        self.client
            .partition_released(proto::PartitionReleasedRequest {
                consumer_name: self.name.clone(),
                partition: Some(partition.clone()),
            })
            .await
            .expect("partition_released RPC failed");
    }

    fn crash(self) {
        drop(self);
    }
}

/// Spawn a background task that drives a consumer's gRPC stream,
/// responding to Warm/Release commands like a real deduplicator.
fn spawn_consumer_driver(
    mut consumer: SimulatedConsumer,
    warm_delay: Duration,
) -> JoinHandle<SimulatedConsumer> {
    tokio::spawn(async move {
        loop {
            let cmd = tokio::time::timeout(Duration::from_secs(1), consumer.next_command()).await;
            match cmd {
                Ok(Some(Command::Assignment(update))) => {
                    consumer.apply_assignment(&update);
                }
                Ok(Some(Command::Warm(warm))) => {
                    consumer.handle_warm(&warm, warm_delay).await;
                }
                Ok(Some(Command::Release(release))) => {
                    consumer.handle_release(&release).await;
                }
                Ok(None) => break,
                Err(_) => continue,
            }
        }
        consumer
    })
}

// ── Basic gRPC scenarios ────────────────────────────────────────

#[tokio::test]
async fn grpc_single_consumer_gets_assignments() {
    let store = test_store("grpc-single").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let _c0_driver = spawn_consumer_driver(c0, Duration::ZERO);

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), NUM_PARTITIONS as usize);
    assert!(assignments.iter().all(|a| a.owner == "c-0"));

    let handoffs = store.list_handoffs().await.unwrap();
    assert!(handoffs.is_empty());

    cancel.cancel();
}

#[tokio::test]
async fn grpc_two_consumers_split_partitions() {
    let store = test_store("grpc-two-split").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    // Register both consumers before starting assigner (no handoffs needed).
    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let c1 = SimulatedConsumer::connect(server.addr, "c-1").await;
    let _c0_driver = spawn_consumer_driver(c0, Duration::ZERO);
    let _c1_driver = spawn_consumer_driver(c1, Duration::ZERO);

    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let has_c0 = assignments.iter().any(|a| a.owner == "c-0");
            let has_c1 = assignments.iter().any(|a| a.owner == "c-1");
            assignments.len() == NUM_PARTITIONS as usize && has_c0 && has_c1
        }
    })
    .await;

    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(assignments.len(), NUM_PARTITIONS as usize);
    assert_eq!(
        assignments.iter().filter(|a| a.owner == "c-0").count(),
        NUM_PARTITIONS as usize / 2
    );
    assert_eq!(
        assignments.iter().filter(|a| a.owner == "c-1").count(),
        NUM_PARTITIONS as usize / 2
    );

    let handoffs = store.list_handoffs().await.unwrap();
    assert!(handoffs.is_empty());

    cancel.cancel();
}

#[tokio::test]
async fn grpc_full_handoff_lifecycle() {
    let store = test_store("grpc-handoff").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let _c0_driver = spawn_consumer_driver(c0, Duration::ZERO);

    // Wait for c-0 to own all partitions.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Register second consumer — triggers handoffs.
    // The consumer driver handles WarmPartition → PartitionReady
    // and the c0 driver handles ReleasePartition → PartitionReleased.
    let c1 = SimulatedConsumer::connect(server.addr, "c-1").await;
    let _c1_driver = spawn_consumer_driver(c1, Duration::ZERO);

    // Wait for handoffs to complete and assignments to balance.
    let check_store = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(15), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            handoffs.is_empty()
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().any(|a| a.owner == "c-0")
                && assignments.iter().any(|a| a.owner == "c-1")
        }
    })
    .await;

    let assignments = store.list_assignments().await.unwrap();
    let c0_count = assignments.iter().filter(|a| a.owner == "c-0").count();
    let c1_count = assignments.iter().filter(|a| a.owner == "c-1").count();
    assert_eq!(c0_count, NUM_PARTITIONS as usize / 2);
    assert_eq!(c1_count, NUM_PARTITIONS as usize / 2);

    cancel.cancel();
}

// ── Deduplicator simulation ─────────────────────────────────────

#[tokio::test]
async fn grpc_checkpoint_download_delay() {
    let store = test_store("grpc-warm-delay").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let _c0_driver = spawn_consumer_driver(c0, Duration::ZERO);

    // Wait for c-0 to own all partitions.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Register c-1 with a 2-second warm-up delay (simulating S3 download).
    let c1 = SimulatedConsumer::connect(server.addr, "c-1").await;
    let _c1_driver = spawn_consumer_driver(c1, Duration::from_secs(2));

    // Wait for handoffs to appear at Warming phase.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            !handoffs.is_empty() && handoffs.iter().all(|h| h.phase == HandoffPhase::Warming)
        }
    })
    .await;

    // Handoffs should stay at Warming for at least ~1 second (during download).
    tokio::time::sleep(Duration::from_secs(1)).await;
    let handoffs = store.list_handoffs().await.unwrap();
    assert!(
        handoffs.iter().all(|h| h.phase == HandoffPhase::Warming),
        "handoffs should still be warming during checkpoint download"
    );

    // Wait for full completion (driven by consumer drivers).
    let check_store = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(20), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            handoffs.is_empty()
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().any(|a| a.owner == "c-0")
                && assignments.iter().any(|a| a.owner == "c-1")
        }
    })
    .await;

    let assignments = store.list_assignments().await.unwrap();
    assert_eq!(
        assignments.iter().filter(|a| a.owner == "c-0").count(),
        NUM_PARTITIONS as usize / 2
    );
    assert_eq!(
        assignments.iter().filter(|a| a.owner == "c-1").count(),
        NUM_PARTITIONS as usize / 2
    );

    cancel.cancel();
}

// ── Disaster scenarios ──────────────────────────────────────────

#[tokio::test]
async fn grpc_crash_during_warming() {
    let store = test_store("grpc-crash-warm").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let _c0_driver = spawn_consumer_driver(c0, Duration::ZERO);

    // Wait for c-0 to own all partitions.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Snapshot stable assignments.
    let stable_assignments: HashMap<u32, String> = store
        .list_assignments()
        .await
        .unwrap()
        .into_iter()
        .map(|a| (a.partition, a.owner))
        .collect();

    // Register c-1 but do NOT drive the handoff — connect and wait for
    // Warming handoffs, then crash before calling PartitionReady.
    let c1 = SimulatedConsumer::connect(server.addr, "c-1").await;

    // Wait for Warming handoffs targeting c-1.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            !handoffs.is_empty()
                && handoffs
                    .iter()
                    .all(|h| h.new_owner == "c-1" && h.phase == HandoffPhase::Warming)
        }
    })
    .await;

    // Crash c-1 — drops the gRPC stream. The server detects the closed
    // channel, revokes the etcd lease, and the consumer disappears.
    c1.crash();

    // Stale handoffs targeting dead c-1 should be cleaned up.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Assignments should revert — all owned by c-0.
    let final_assignments: HashMap<u32, String> = store
        .list_assignments()
        .await
        .unwrap()
        .into_iter()
        .map(|a| (a.partition, a.owner))
        .collect();
    assert_eq!(final_assignments, stable_assignments);

    cancel.cancel();
}

#[tokio::test]
async fn grpc_consumer_crashes_mid_operation() {
    let store = test_store("grpc-crash-mid").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let _c0_driver = spawn_consumer_driver(c0, Duration::ZERO);
    let c1 = SimulatedConsumer::connect(server.addr, "c-1").await;
    let c1_driver = spawn_consumer_driver(c1, Duration::ZERO);

    // Wait for balanced assignment with both consumers (drive handoffs).
    let check_store = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(15), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            handoffs.is_empty()
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().any(|a| a.owner == "c-0")
                && assignments.iter().any(|a| a.owner == "c-1")
        }
    })
    .await;

    // Kill c-1's driver (simulating pod crash while actively processing).
    // Dropping the driver drops the SimulatedConsumer, closing the gRPC stream.
    c1_driver.abort();

    // Wait for c-1 to disappear and all partitions to converge to c-0.
    // The c-0 driver handles WarmPartition commands for incoming partitions.
    // Complete-phase handoffs with dead old_owner (c-1) are auto-cleaned.
    let check_store = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(15), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            handoffs.is_empty()
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    cancel.cancel();
}

#[tokio::test]
async fn grpc_rapid_reconnect() {
    let store = test_store("grpc-reconnect").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let c0_driver = spawn_consumer_driver(c0, Duration::ZERO);

    // Wait for c-0 to own all partitions.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Disconnect by aborting the driver (drops the stream).
    c0_driver.abort();

    // Immediately reconnect with the same consumer name.
    let c0_new = SimulatedConsumer::connect(server.addr, "c-0").await;
    let _c0_new_driver = spawn_consumer_driver(c0_new, Duration::ZERO);

    // Wait for the consumer to be registered and all partitions assigned.
    // There may be a brief window where the old lease is revoked and the
    // new one isn't yet seen by the assigner, so partitions may briefly
    // be unassigned. The system should converge.
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let consumers = store.list_consumers().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            consumers.iter().any(|c| c.consumer_name == "c-0")
                && handoffs.is_empty()
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    cancel.cancel();
}

#[tokio::test]
async fn grpc_sequential_crashes_converge() {
    let store = test_store("grpc-seq-crash").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    // Start 3 consumers.
    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let _c0_driver = spawn_consumer_driver(c0, Duration::ZERO);
    let c1 = SimulatedConsumer::connect(server.addr, "c-1").await;
    let c1_driver = spawn_consumer_driver(c1, Duration::ZERO);
    let c2 = SimulatedConsumer::connect(server.addr, "c-2").await;
    let c2_driver = spawn_consumer_driver(c2, Duration::ZERO);

    // Wait for 3-way assignment (all consumers have partitions, no handoffs).
    let check_store = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(20), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            handoffs.is_empty()
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().any(|a| a.owner == "c-0")
                && assignments.iter().any(|a| a.owner == "c-1")
                && assignments.iter().any(|a| a.owner == "c-2")
        }
    })
    .await;

    // Crash c-2.
    c2_driver.abort();

    // Wait for convergence to c-0 + c-1.
    let check_store = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(20), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            handoffs.is_empty()
                && assignments.len() == NUM_PARTITIONS as usize
                && !assignments.iter().any(|a| a.owner == "c-2")
                && assignments.iter().any(|a| a.owner == "c-0")
                && assignments.iter().any(|a| a.owner == "c-1")
        }
    })
    .await;

    // Crash c-1.
    c1_driver.abort();

    // Wait for convergence to c-0 only.
    let check_store = Arc::clone(&store);
    wait_for_condition(Duration::from_secs(20), POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            handoffs.is_empty()
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    cancel.cancel();
}

// ── Large-scale scenarios ───────────────────────────────────────

const LARGE_NUM_CONSUMERS: usize = 20;
const LARGE_NUM_PARTITIONS: u32 = 40;
const LARGE_TIMEOUT: Duration = Duration::from_secs(60);

#[tokio::test]
async fn grpc_fast_scale_to_20() {
    let store = test_store("grpc-scale-20").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", LARGE_NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    // Register first consumer and wait for it to own all partitions.
    let c0 = SimulatedConsumer::connect(server.addr, "c-0").await;
    let mut drivers: Vec<JoinHandle<SimulatedConsumer>> =
        vec![spawn_consumer_driver(c0, Duration::ZERO)];

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == LARGE_NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "c-0")
        }
    })
    .await;

    // Rapidly register 19 more consumers.
    for i in 1..LARGE_NUM_CONSUMERS {
        let name = format!("c-{i}");
        let c = SimulatedConsumer::connect(server.addr, &name).await;
        drivers.push(spawn_consumer_driver(c, Duration::ZERO));
    }

    // Wait for convergence: 40 partitions / 20 consumers = 2 each.
    let consumer_names: Vec<String> = (0..LARGE_NUM_CONSUMERS).map(|i| format!("c-{i}")).collect();
    let check_store = Arc::clone(&store);
    wait_for_condition(LARGE_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        let names = consumer_names.clone();
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            if !handoffs.is_empty() || assignments.len() != LARGE_NUM_PARTITIONS as usize {
                return false;
            }

            names
                .iter()
                .all(|name| assignments.iter().any(|a| a.owner == *name))
        }
    })
    .await;

    // Verify even distribution: each consumer owns exactly 2 partitions.
    let assignments = store.list_assignments().await.unwrap();
    let per_consumer = LARGE_NUM_PARTITIONS as usize / LARGE_NUM_CONSUMERS;
    for name in &consumer_names {
        assert_eq!(
            assignments.iter().filter(|a| a.owner == *name).count(),
            per_consumer,
            "expected {name} to own exactly {per_consumer} partitions"
        );
    }

    cancel.cancel();
}

#[tokio::test]
async fn grpc_fast_scale_down_20_to_4() {
    let store = test_store("grpc-scale-down").await;
    let cancel = CancellationToken::new();

    set_topic_config(&store, "events", LARGE_NUM_PARTITIONS).await;
    let _assigner = start_assigner(Arc::clone(&store), cancel.clone());
    let server = start_grpc_server(Arc::clone(&store), cancel.clone()).await;

    // Register all 20 consumers.
    let mut drivers: BTreeMap<String, JoinHandle<SimulatedConsumer>> = BTreeMap::new();
    for i in 0..LARGE_NUM_CONSUMERS {
        let name = format!("c-{i}");
        let c = SimulatedConsumer::connect(server.addr, &name).await;
        drivers.insert(name, spawn_consumer_driver(c, Duration::ZERO));
    }

    // Wait for initial convergence: all 20 consumers have partitions.
    let consumer_names: Vec<String> = (0..LARGE_NUM_CONSUMERS).map(|i| format!("c-{i}")).collect();
    let check_store = Arc::clone(&store);
    wait_for_condition(LARGE_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        let names = consumer_names.clone();
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            handoffs.is_empty()
                && assignments.len() == LARGE_NUM_PARTITIONS as usize
                && names
                    .iter()
                    .all(|name| assignments.iter().any(|a| a.owner == *name))
        }
    })
    .await;

    // Crash consumers c-4 through c-19 (keep c-0 to c-3).
    let survivors: HashSet<String> = (0..4).map(|i| format!("c-{i}")).collect();
    for (name, driver) in &drivers {
        if !survivors.contains(name) {
            driver.abort();
        }
    }

    // Wait for convergence: only survivors remain, each with 10 partitions
    // (40 partitions / 4 consumers = 10 each).
    let check_store = Arc::clone(&store);
    let check_survivors = survivors.clone();
    wait_for_condition(LARGE_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        let survivors = check_survivors.clone();
        async move {
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            if !handoffs.is_empty() || assignments.len() != LARGE_NUM_PARTITIONS as usize {
                return false;
            }

            let owners: HashSet<String> = assignments.iter().map(|a| a.owner.clone()).collect();
            owners == survivors
        }
    })
    .await;

    // Verify even distribution: each survivor owns exactly 10 partitions.
    let assignments = store.list_assignments().await.unwrap();
    let per_survivor = LARGE_NUM_PARTITIONS as usize / survivors.len();
    for name in &survivors {
        assert_eq!(
            assignments.iter().filter(|a| a.owner == *name).count(),
            per_survivor,
            "expected {name} to own exactly {per_survivor} partitions"
        );
    }

    cancel.cancel();
}
