mod common;

use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;

use common::{
    create_leader_client, create_local_kafka_producer, create_test_kafka,
    create_test_kafka_with_partitions, person_id_for_partition, seed_person, start_coordinator,
    start_leader_pod, start_leader_pod_with_lease_ttl, start_leader_with_pg_fallback, start_router,
    test_cached_person, test_recovery, test_store, test_warming_config, wait_for_condition,
    CHANGELOG_TOPIC, KAFKA_BOOTSTRAP, NUM_PARTITIONS, POLL_INTERVAL, WAIT_TIMEOUT,
};
use personhog_common::partitioning::partition_for_person;
use personhog_coordination::pod::HandoffHandler;
use personhog_coordination::strategy::StickyBalancedStrategy;
use personhog_leader::cache::{
    CacheLookup, CachedPerson, DirtyIndex, DirtyMark, PartitionedCache, PersonCacheKey,
};
use personhog_leader::coordination::LeaderHandoffHandler;
use personhog_leader::inflight::InflightTracker;
use personhog_leader::service::PersonHogLeaderService;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use personhog_proto::personhog::types::v1::{
    GetPersonRequest, Person, UpdatePersonPropertiesRequest,
};
use prost::Message;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::types::{RDKafkaApiKey, RDKafkaRespErr};
use rdkafka::{ClientConfig, Message as KafkaMessage, TopicPartitionList};
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use tonic::transport::Server;
use tonic::Request;

/// Wrap a request with the `x-partition` metadata the leader reads in place
/// of a body field, matching how the router forwards to the leader.
fn with_partition<T>(req: T, partition: u32) -> Request<T> {
    let mut request = Request::new(req);
    request
        .metadata_mut()
        .insert("x-partition", partition.to_string().parse().unwrap());
    request
}

/// Build a `GetPerson` request carrying the partition in `x-partition`
/// metadata, matching how the router forwards strong reads to the leader.
fn leader_get_request(team_id: i64, person_id: i64, partition: u32) -> Request<GetPersonRequest> {
    with_partition(
        GetPersonRequest {
            team_id,
            person_id,
            read_options: None,
        },
        partition,
    )
}

// ============================================================
// Test 1: Full lifecycle via etcd coordination
// ============================================================

#[tokio::test]
async fn service_accepts_requests_after_coordination_warmup() {
    let store = test_store("leader-warmup").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Single pod gets all partitions
    let pod = start_leader_pod(Arc::clone(&store), "leader-0", 100, cancel.clone()).await;

    // Wait for all partitions to be assigned
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "leader-0")
        }
    })
    .await;

    // Wait for handoffs to complete (warmup finished)
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move { store.list_handoffs().await.unwrap_or_default().is_empty() }
    })
    .await;

    // Wait for all partitions to be warmed in the cache (may lag behind etcd state)
    let check_cache = Arc::clone(&pod.cache);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let cache = Arc::clone(&check_cache);
        async move { (0..NUM_PARTITIONS).all(|p| cache.has_partition(p)) }
    })
    .await;

    // Seed a person into partition 0
    let person = test_cached_person();
    seed_person(&pod.cache, 0, person.clone());

    // gRPC get_person should succeed
    let mut client = create_leader_client(pod.leader_addr).await;
    let response = client
        .get_person(leader_get_request(1, 42, 0))
        .await
        .unwrap();

    let proto_person = response.into_inner().person.unwrap();
    assert_eq!(proto_person.id, 42);
    assert_eq!(proto_person.team_id, 1);

    // Update should succeed
    let response = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: 42,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"name": "Updated"}))
                    .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            0,
        ))
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);
    assert_eq!(result.person.unwrap().version, 2);

    // Read back should reflect the update
    let response = client
        .get_person(leader_get_request(1, 42, 0))
        .await
        .unwrap();

    let proto_person = response.into_inner().person.unwrap();
    assert_eq!(proto_person.version, 2);

    let props: serde_json::Value = serde_json::from_slice(&proto_person.properties).unwrap();
    assert_eq!(props["name"], "Updated");
    assert_eq!(props["email"], "test@example.com");

    cancel.cancel();
}

// ============================================================
// Test 2: Unowned partition returns FailedPrecondition
// (no etcd needed)
// ============================================================

#[tokio::test]
async fn unowned_partition_returns_failed_precondition() {
    // Create service + cache directly, no coordination
    let cache = Arc::new(PartitionedCache::new(100));
    let (_mock_cluster, kafka_producer) = create_test_kafka().await;
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(KAFKA_BOOTSTRAP),
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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
    tokio::time::sleep(std::time::Duration::from_millis(10)).await;

    let mut client = create_leader_client(addr).await;

    // Request for unowned partition → FailedPrecondition
    let result = client.get_person(leader_get_request(1, 42, 0)).await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::FailedPrecondition);

    // Write to unowned partition → FailedPrecondition
    let result = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: 42,
                event_name: "$set".to_string(),
                set_properties: vec![],
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            0,
        ))
        .await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::FailedPrecondition);

    // Manually warm partition → now NotFound (partition exists, no data)
    cache.create_partition(0);

    let result = client.get_person(leader_get_request(1, 42, 0)).await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::NotFound);

    cancel.cancel();
}

// ============================================================
// Test 2b: Requests without x-partition metadata fail closed
// (no etcd needed)
// ============================================================

/// The partition arrives only via `x-partition` metadata, stamped by the
/// router. A request without it is misrouted or malformed and must be
/// rejected with INVALID_ARGUMENT rather than served against a guessed
/// partition — even when the person exists and its partition is warm.
#[tokio::test]
async fn missing_partition_metadata_returns_invalid_argument() {
    let cache = Arc::new(PartitionedCache::new(100));
    let (_mock_cluster, kafka_producer) = create_test_kafka().await;
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(KAFKA_BOOTSTRAP),
    );

    // Warm the partition and seed the person so the only failure mode
    // left is the missing metadata itself.
    cache.create_partition(0);
    seed_person(&cache, 0, test_cached_person());

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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

    let mut client = create_leader_client(addr).await;

    let result = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        })
        .await;
    let status = result.expect_err("read without x-partition must fail closed");
    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("x-partition"));

    let result = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: vec![],
            set_once_properties: vec![],
            unset_properties: vec![],
        })
        .await;
    let status = result.expect_err("write without x-partition must fail closed");
    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("x-partition"));

    cancel.cancel();
}

// ============================================================
// Test 2c: x-partition must match the partition derived from the
// request's own key (no etcd needed)
// ============================================================

/// The leader validates the router's routing decision against the decoded
/// body: `x-partition` must equal `partition_for_person(team_id,
/// person_id)`. A mismatch means a client stamped wrong routing-key
/// headers or the hash implementations diverged — serving it would read or
/// write through the wrong partition's cache, so it must be rejected even
/// when the named partition is warm and the person exists there.
#[tokio::test]
async fn mismatched_partition_metadata_returns_invalid_argument() {
    let cache = Arc::new(PartitionedCache::new(100));
    let (_mock_cluster, kafka_producer) = create_test_kafka().await;
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(KAFKA_BOOTSTRAP),
    );

    // Key (1, 42) hashes to some true partition; pick a different one and
    // warm + seed it so the only failure mode left is the mismatch itself.
    let true_partition = partition_for_person(1, 42, NUM_PARTITIONS);
    let wrong_partition = (true_partition + 1) % NUM_PARTITIONS;
    cache.create_partition(wrong_partition);
    seed_person(&cache, wrong_partition, test_cached_person());

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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

    let mut client = create_leader_client(addr).await;

    let result = client
        .get_person(leader_get_request(1, 42, wrong_partition))
        .await;
    let status = result.expect_err("read with mismatched x-partition must fail closed");
    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("does not match"));

    let result = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: 42,
                event_name: "$set".to_string(),
                set_properties: vec![],
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            wrong_partition,
        ))
        .await;
    let status = result.expect_err("write with mismatched x-partition must fail closed");
    assert_eq!(status.code(), tonic::Code::InvalidArgument);
    assert!(status.message().contains("does not match"));

    cancel.cancel();
}

// ============================================================
// Test 2b: Post-drain write fencing
// (no etcd needed)
// ============================================================

/// Once the old owner has drained a partition, every router has acked the
/// freeze — so a later write can only come from a router serving with a
/// stale table (an expired lease it hasn't noticed, a missed freeze).
/// Accepting it would produce to Kafka past the HWM that warming
/// snapshots, silently losing the write from the new owner's cache. After
/// draining, the old owner must reject writes for the partition while
/// continuing to serve reads: the frozen state remains the latest until
/// cutover. Releasing the partition clears the fence with it.
#[tokio::test]
async fn writes_fenced_after_drain_reads_still_served() {
    let cache = Arc::new(PartitionedCache::new(100));
    let (_mock_cluster, kafka_producer) = create_test_kafka().await;
    let inflight = Arc::new(InflightTracker::new());
    let dirty_index = Arc::new(DirtyIndex::new(1_000_000));
    let recovery = test_recovery(KAFKA_BOOTSTRAP);
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::clone(&inflight),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        Arc::clone(&recovery),
    );
    // The handler shares the cache, inflight tracker, dirty index, and
    // recovery pool with the service, exactly as main.rs wires them.
    let handler = LeaderHandoffHandler::new(
        Arc::clone(&cache),
        Arc::clone(&inflight),
        Arc::clone(&dirty_index),
        test_warming_config("fence-pod", KAFKA_BOOTSTRAP),
    );

    cache.create_partition(0);
    seed_person(&cache, 0, test_cached_person());

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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

    let mut client = create_leader_client(addr).await;

    let update = |email: &str| {
        with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: 42,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({ "email": email })).unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            0,
        )
    };

    // Pre-drain: writes flow normally.
    let response = client
        .update_person_properties(update("before@example.com"))
        .await
        .unwrap();
    assert!(response.into_inner().updated);

    // Drain the partition, as the pod does on observing Draining.
    handler.drain_partition_inflight(0).await.unwrap();

    // Post-drain: writes must be fenced…
    let status = client
        .update_person_properties(update("after@example.com"))
        .await
        .expect_err("write after drain must be rejected");
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);

    // …while reads keep serving the frozen, still-latest state.
    let response = client
        .get_person(leader_get_request(1, 42, 0))
        .await
        .expect("reads must keep serving after drain");
    let props: serde_json::Value =
        serde_json::from_slice(&response.into_inner().person.unwrap().properties).unwrap();
    assert_eq!(props["email"], "before@example.com");

    // Releasing clears the fence along with the partition: when the same
    // pod later re-acquires the partition (fresh warm), writes flow again.
    handler.release_partition(0).await.unwrap();
    cache.create_partition(0);
    seed_person(&cache, 0, test_cached_person());
    let response = client
        .update_person_properties(update("rewarmed@example.com"))
        .await
        .expect("writes must flow again after release + re-warm");
    assert!(response.into_inner().updated);

    cancel.cancel();
}

/// The fence must go up before the drain starts waiting on inflight
/// handlers — fencing only after `wait_until_empty` returns would leave a
/// window where a write lands between the inflight count hitting zero and
/// the DrainedAck being written, advancing the Kafka HWM past what
/// warming will read. With an inflight write held open, new writes must
/// already be rejected while the drain is still waiting.
#[tokio::test]
async fn drain_fences_before_waiting_on_inflight() {
    let cache = Arc::new(PartitionedCache::new(100));
    let (_mock_cluster, kafka_producer) = create_test_kafka().await;
    let inflight = Arc::new(InflightTracker::new());
    let dirty_index = Arc::new(DirtyIndex::new(1_000_000));
    let recovery = test_recovery(KAFKA_BOOTSTRAP);
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::clone(&inflight),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        Arc::clone(&recovery),
    );
    let handler = Arc::new(LeaderHandoffHandler::new(
        Arc::clone(&cache),
        Arc::clone(&inflight),
        Arc::clone(&dirty_index),
        test_warming_config("fence-race-pod", KAFKA_BOOTSTRAP),
    ));

    cache.create_partition(0);
    seed_person(&cache, 0, test_cached_person());

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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

    let mut client = create_leader_client(addr).await;

    // Hold a simulated in-flight write so the drain parks in
    // wait_until_empty rather than completing immediately.
    let guard = inflight.begin(0);

    let drain_handler = Arc::clone(&handler);
    let drain = tokio::spawn(async move { drain_handler.drain_partition_inflight(0).await });

    // Give the drain a moment to start waiting.
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert!(
        !drain.is_finished(),
        "drain must wait for the held inflight"
    );

    // A write arriving mid-drain must already be fenced.
    let status = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: 42,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(
                    &serde_json::json!({"email": "mid@example.com"}),
                )
                .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            0,
        ))
        .await
        .expect_err("write during drain must be rejected");
    assert_eq!(status.code(), tonic::Code::FailedPrecondition);

    // Releasing the held write lets the drain complete.
    drop(guard);
    tokio::time::timeout(Duration::from_secs(5), drain)
        .await
        .expect("drain must complete once inflight reaches zero")
        .expect("drain task must not panic")
        .expect("drain must succeed");

    cancel.cancel();
}

// ============================================================
// Test 3: Release partition stops serving
// ============================================================

#[tokio::test]
async fn release_partition_stops_serving() {
    let store = test_store("leader-release").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Start pod 1 — gets all partitions
    let pod1 = start_leader_pod(Arc::clone(&store), "leader-0", 100, cancel.clone()).await;

    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "leader-0")
                && handoffs.is_empty()
        }
    })
    .await;

    // Wait for cache to reflect assignments (may lag behind etcd state)
    let check_cache = Arc::clone(&pod1.cache);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let cache = Arc::clone(&check_cache);
        async move { (0..NUM_PARTITIONS).all(|p| cache.has_partition(p)) }
    })
    .await;

    // Seed a person into partition 0
    seed_person(&pod1.cache, 0, test_cached_person());

    // Verify get_person works on pod 1
    let mut client1 = create_leader_client(pod1.leader_addr).await;
    let response = client1
        .get_person(leader_get_request(1, 42, 0))
        .await
        .unwrap();
    assert_eq!(response.into_inner().person.unwrap().id, 42);

    // Start pod 2 — triggers rebalance
    let pod2 = start_leader_pod(Arc::clone(&store), "leader-1", 100, cancel.clone()).await;

    // Wait for balanced assignment and handoffs to settle
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let has_both = assignments.iter().any(|a| a.owner == "leader-0")
                && assignments.iter().any(|a| a.owner == "leader-1");
            assignments.len() == NUM_PARTITIONS as usize && has_both && handoffs.is_empty()
        }
    })
    .await;

    // Find a partition that moved from pod 1 to pod 2
    let assignments = store.list_assignments().await.unwrap();
    let moved_partition = assignments
        .iter()
        .find(|a| a.owner == "leader-1")
        .expect("pod 2 should own at least one partition")
        .partition;

    // Wait for caches to reflect the rebalance (may lag behind etcd state)
    let check_cache1 = Arc::clone(&pod1.cache);
    let check_cache2 = Arc::clone(&pod2.cache);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let c1 = Arc::clone(&check_cache1);
        let c2 = Arc::clone(&check_cache2);
        async move { !c1.has_partition(moved_partition) && c2.has_partition(moved_partition) }
    })
    .await;

    // A key that actually hashes to the moved partition, so the request
    // passes the leader's partition validation.
    let moved_person_id = person_id_for_partition(1, moved_partition);

    // Pod 1: released partition → FailedPrecondition
    let result = client1
        .get_person(leader_get_request(1, moved_person_id, moved_partition))
        .await;
    assert!(result.is_err());
    assert_eq!(
        result.unwrap_err().code(),
        tonic::Code::FailedPrecondition,
        "pod 1 should reject requests for released partition {moved_partition}"
    );

    // Pod 2: warmed partition but empty cache → NotFound
    let mut client2 = create_leader_client(pod2.leader_addr).await;
    let result = client2
        .get_person(leader_get_request(1, moved_person_id, moved_partition))
        .await;
    assert!(result.is_err());
    assert_eq!(
        result.unwrap_err().code(),
        tonic::Code::NotFound,
        "pod 2 should have partition {moved_partition} warmed but no data"
    );

    cancel.cancel();
}

// ============================================================
// Test 4: Rewarm after pod crash
// ============================================================

#[tokio::test]
async fn rewarm_after_pod_crash() {
    let store = test_store("leader-rewarm").await;
    let cancel = CancellationToken::new();

    store.set_total_partitions(NUM_PARTITIONS).await.unwrap();

    let _coord = start_coordinator(
        Arc::clone(&store),
        Arc::new(StickyBalancedStrategy),
        cancel.clone(),
    );
    let _router = start_router(Arc::clone(&store), "router-0", cancel.clone());

    // Pod 1 with short lease (crash detectable quickly)
    let pod1_cancel = CancellationToken::new();
    let _pod1 = start_leader_pod_with_lease_ttl(
        Arc::clone(&store),
        "leader-0",
        100,
        2,
        pod1_cancel.clone(),
    )
    .await;

    // Pod 2 (long-lived)
    let pod2 = start_leader_pod(Arc::clone(&store), "leader-1", 100, cancel.clone()).await;

    // Wait for balanced assignment
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            let has_both = assignments.iter().any(|a| a.owner == "leader-0")
                && assignments.iter().any(|a| a.owner == "leader-1");
            assignments.len() == NUM_PARTITIONS as usize && has_both && handoffs.is_empty()
        }
    })
    .await;

    // Kill pod 1
    pod1_cancel.cancel();

    // Wait for pod 1 to disappear and all partitions to move to pod 2
    let check_store = Arc::clone(&store);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let store = Arc::clone(&check_store);
        async move {
            let pods = store.list_pods().await.unwrap_or_default();
            let assignments = store.list_assignments().await.unwrap_or_default();
            let handoffs = store.list_handoffs().await.unwrap_or_default();
            pods.len() == 1
                && assignments.len() == NUM_PARTITIONS as usize
                && assignments.iter().all(|a| a.owner == "leader-1")
                && handoffs.is_empty()
        }
    })
    .await;

    // Wait for pod 2 to re-warm all partitions (may lag behind etcd state)
    let check_cache = Arc::clone(&pod2.cache);
    wait_for_condition(WAIT_TIMEOUT, POLL_INTERVAL, || {
        let cache = Arc::clone(&check_cache);
        async move { (0..NUM_PARTITIONS).all(|p| cache.has_partition(p)) }
    })
    .await;

    // Partitions are warm but empty → NotFound
    let mut client2 = create_leader_client(pod2.leader_addr).await;
    let result = client2.get_person(leader_get_request(1, 42, 0)).await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::NotFound);

    cancel.cancel();
}

// ============================================================
// Test 5: Successful update produces person state to Kafka
// (no etcd needed)
// ============================================================

#[tokio::test]
async fn update_produces_person_state_to_kafka() {
    // The changelog must land on the exact Kafka partition the request's
    // `x-partition` named — warming rebuilds a routing partition's cache by
    // consuming the same-numbered Kafka partition, so key-hash placement
    // (whose partitioner config could diverge from the router's murmur2)
    // is not acceptable. The key (team 1, person 2) murmur2-hashes to
    // partition 2 (so it passes the leader's partition validation) but
    // librdkafka's default crc32 partitioner would place it on partition 0,
    // keeping misplacement observable: the consumer below reads only
    // partition 2 and must find the message there.
    const PERSON_ID: i64 = 2;
    let routing_partition: u32 = partition_for_person(1, PERSON_ID, NUM_PARTITIONS);
    assert_eq!(routing_partition, 2, "test key must map to partition 2");
    let (mock_cluster, kafka_producer) = create_test_kafka_with_partitions(4).await;

    let cache = Arc::new(PartitionedCache::new(100));
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(KAFKA_BOOTSTRAP),
    );

    cache.create_partition(routing_partition);
    let person = CachedPerson {
        id: PERSON_ID,
        ..test_cached_person()
    };
    seed_person(&cache, routing_partition, person);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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

    let mut client = create_leader_client(addr).await;

    // Perform an update
    let response = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: PERSON_ID,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"name": "Kafka Test"}))
                    .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            routing_partition,
        ))
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);
    assert_eq!(result.person.unwrap().version, 2);

    // Consume only the routing partition — finding the message here proves
    // the explicit-partition produce, not just delivery.
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "test-consumer")
        .create()
        .expect("failed to create consumer");

    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(
        CHANGELOG_TOPIC,
        routing_partition as i32,
        rdkafka::Offset::Beginning,
    )
    .unwrap();
    consumer.assign(&tpl).unwrap();

    let msg = consumer
        .poll(Duration::from_secs(5))
        .expect("no message received on the routing partition")
        .expect("kafka error");

    // Verify message key
    let key = std::str::from_utf8(msg.key().unwrap()).unwrap();
    assert_eq!(key, "1:2");

    // Verify payload is a valid Person proto with updated state
    let person = Person::decode(msg.payload().unwrap()).unwrap();
    assert_eq!(person.id, PERSON_ID);
    assert_eq!(person.team_id, 1);
    assert_eq!(person.version, 2);

    let props: serde_json::Value = serde_json::from_slice(&person.properties).unwrap();
    assert_eq!(props["name"], "Kafka Test");
    assert_eq!(props["email"], "test@example.com");

    cancel.cancel();
}

// ============================================================
// Test 6: Kafka produce failure leaves cache unchanged and returns error
// (no etcd needed)
// ============================================================

#[tokio::test]
async fn kafka_produce_failure_leaves_cache_unchanged() {
    let cache = Arc::new(PartitionedCache::new(100));
    let (mock_cluster, kafka_producer) = create_test_kafka().await;

    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(KAFKA_BOOTSTRAP),
    );

    cache.create_partition(0);
    let person = test_cached_person();
    seed_person(&cache, 0, person);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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

    // Inject a Kafka produce error
    let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR__BAD_MSG; 1];
    mock_cluster.request_errors(RDKafkaApiKey::Produce, &err);

    let mut client = create_leader_client(addr).await;

    // Update should fail because Kafka produce fails
    let result = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: 42,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"name": "Should Rollback"}))
                    .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            0,
        ))
        .await;

    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::Internal);

    // Cache was never updated since the produce failed before the cache write
    let cache_key = PersonCacheKey {
        team_id: 1,
        person_id: 42,
    };
    let CacheLookup::Found(cached) = cache.get(0, &cache_key) else {
        panic!("expected original person in cache");
    };
    assert_eq!(cached.version, 1);
    assert_eq!(cached.properties["email"], "test@example.com");
    assert!(cached.properties.get("name").is_none());

    // Clear errors and verify the service recovers
    mock_cluster.clear_request_errors(RDKafkaApiKey::Produce);

    let response = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: 42,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"name": "After Recovery"}))
                    .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            0,
        ))
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);
    assert_eq!(result.person.unwrap().version, 2);

    cancel.cancel();
}

// ============================================================
// Test 7: E2E - update produces to local Kafka and is consumable
// Requires local Kafka (localhost:9092) and etcd running.
// ============================================================

#[tokio::test]
async fn e2e_update_produces_to_local_kafka() {
    let cache = Arc::new(PartitionedCache::new(100));
    let kafka_producer = create_local_kafka_producer().await;

    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::new(DirtyIndex::new(1_000_000)),
        test_recovery(KAFKA_BOOTSTRAP),
    );

    cache.create_partition(0);
    let person = test_cached_person();
    seed_person(&cache, 0, person);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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

    let mut client = create_leader_client(addr).await;

    // Perform an update via gRPC
    let response = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: 42,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"name": "E2E Test"}))
                    .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            0,
        ))
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);
    assert_eq!(result.person.unwrap().version, 2);

    // Consume from local Kafka and verify the message
    let consumer: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BOOTSTRAP)
        .set("group.id", format!("e2e-test-{}", uuid::Uuid::new_v4()))
        .create()
        .expect("failed to create local Kafka consumer");

    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(CHANGELOG_TOPIC, 0, rdkafka::Offset::End)
        .unwrap();
    consumer.assign(&tpl).unwrap();

    // Seek back one message from the end to read what we just produced.
    // End offset points past the last message, so we query it and subtract 1.
    let (_, high_watermark) = consumer
        .fetch_watermarks(CHANGELOG_TOPIC, 0, Duration::from_secs(5))
        .expect("failed to fetch watermarks");
    let target_offset = (high_watermark - 1).max(0);

    let mut seek_tpl = TopicPartitionList::new();
    seek_tpl
        .add_partition_offset(CHANGELOG_TOPIC, 0, rdkafka::Offset::Offset(target_offset))
        .unwrap();
    consumer.assign(&seek_tpl).unwrap();

    let msg = consumer
        .poll(Duration::from_secs(5))
        .expect("no message received from local Kafka")
        .expect("kafka error");

    let key = std::str::from_utf8(msg.key().unwrap()).unwrap();
    assert_eq!(key, "1:42");

    let person = Person::decode(msg.payload().unwrap()).unwrap();
    assert_eq!(person.id, 42);
    assert_eq!(person.team_id, 1);
    assert_eq!(person.version, 2);

    let props: serde_json::Value = serde_json::from_slice(&person.properties).unwrap();
    assert_eq!(props["name"], "E2E Test");
    assert_eq!(props["email"], "test@example.com");

    cancel.cancel();
}

// ============================================================
// Test 8: PG fallback on cache miss
// Requires local Postgres with posthog_person data.
// ============================================================

#[tokio::test]
async fn pg_fallback_loads_person_on_cache_miss() {
    let cancel = CancellationToken::new();
    let (addr, cache, _mock_cluster) = start_leader_with_pg_fallback(cancel.clone()).await;

    // Find a real person in the local DB to query
    let pool = common::create_persons_pool().await;
    let row: Option<(i64, i32)> = sqlx::query_as("SELECT id, team_id FROM posthog_person LIMIT 1")
        .fetch_optional(&pool)
        .await
        .unwrap();

    let Some((person_id, team_id)) = row else {
        println!("No persons in posthog_person, skipping PG fallback test");
        cancel.cancel();
        return;
    };

    // Warm the key's own partition (the cache is empty — no persons seeded)
    let partition = partition_for_person(team_id as i64, person_id, NUM_PARTITIONS);
    cache.create_partition(partition);

    let mut client = create_leader_client(addr).await;

    // First call: cache miss → PG fallback → loads and caches the person
    let response = client
        .get_person(leader_get_request(team_id as i64, person_id, partition))
        .await
        .unwrap();

    let person = response.into_inner().person.unwrap();
    assert_eq!(person.id, person_id);
    assert_eq!(person.team_id, team_id as i64);

    // Verify person is now cached
    let key = PersonCacheKey {
        team_id: team_id as i64,
        person_id,
    };
    assert!(
        matches!(cache.get(partition, &key), CacheLookup::Found(_)),
        "person should be cached after PG fallback"
    );

    cancel.cancel();
}

// ============================================================
// Test 9: PG fallback returns NotFound for non-existent person
// ============================================================

#[tokio::test]
async fn pg_fallback_returns_not_found_for_missing_person() {
    let cancel = CancellationToken::new();
    let (addr, cache, _mock_cluster) = start_leader_with_pg_fallback(cancel.clone()).await;

    let partition = partition_for_person(99999, 99999999, NUM_PARTITIONS);
    cache.create_partition(partition);

    let mut client = create_leader_client(addr).await;

    // Query a person that doesn't exist in PG
    let result = client
        .get_person(leader_get_request(99999, 99999999, partition))
        .await;

    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::NotFound);

    cancel.cancel();
}

// ============================================================
// Test 10: Update triggers PG fallback on cache miss then applies changes
// ============================================================

#[tokio::test]
async fn update_triggers_pg_fallback_then_applies_changes() {
    let cancel = CancellationToken::new();
    let (addr, cache, _mock_cluster) = start_leader_with_pg_fallback(cancel.clone()).await;

    // Find a real person to update
    let pool = common::create_persons_pool().await;
    let row: Option<(i64, i32)> = sqlx::query_as("SELECT id, team_id FROM posthog_person LIMIT 1")
        .fetch_optional(&pool)
        .await
        .unwrap();

    let Some((person_id, team_id)) = row else {
        println!("No persons in posthog_person, skipping PG fallback update test");
        cancel.cancel();
        return;
    };

    let partition = partition_for_person(team_id as i64, person_id, NUM_PARTITIONS);
    cache.create_partition(partition);

    let mut client = create_leader_client(addr).await;

    // Update a person not in cache — should load from PG then apply
    let response = client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: team_id as i64,
                person_id,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({
                    "pg_fallback_test": "it_works"
                }))
                .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            partition,
        ))
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);

    let updated_person = result.person.unwrap();
    assert_eq!(updated_person.id, person_id);
    let props: serde_json::Value = serde_json::from_slice(&updated_person.properties).unwrap();
    assert_eq!(props["pg_fallback_test"], "it_works");

    cancel.cancel();
}

// ============================================================
// Dirty-index recovery: eviction of a person whose latest state
// exists only in the changelog must recover from Kafka, never PG
// ============================================================

#[tokio::test]
async fn evicted_dirty_person_recovers_from_changelog() {
    const PERSON_ID: i64 = 2;
    let routing_partition: u32 = partition_for_person(1, PERSON_ID, NUM_PARTITIONS);
    let (mock_cluster, kafka_producer) = create_test_kafka_with_partitions(4).await;

    let cache = Arc::new(PartitionedCache::new(100));
    let dirty_index = Arc::new(DirtyIndex::new(1_000_000));
    // Recovery reads from the same mock broker the update produces to.
    // Deliberately no PG pool: a recovery path that (wrongly) fell back to
    // PG would return NotFound and fail the final assertion.
    let recovery = test_recovery(&mock_cluster.bootstrap_servers());
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        Arc::clone(&recovery),
    );

    cache.create_partition(routing_partition);
    let person = CachedPerson {
        id: PERSON_ID,
        ..test_cached_person()
    };
    seed_person(&cache, routing_partition, person);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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
    let mut client = create_leader_client(addr).await;

    // The update produces the v2 record and marks the dirty index.
    client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: PERSON_ID,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"name": "Recovered"}))
                    .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            routing_partition,
        ))
        .await
        .unwrap();
    assert_eq!(dirty_index.len(), 1, "the acked write must be marked dirty");

    // Simulate eviction of the freshly written entry.
    let key = PersonCacheKey {
        team_id: 1,
        person_id: PERSON_ID,
    };
    cache.remove(routing_partition, &key);

    // The read must return the updated state, recovered from the changelog
    // record at the marked offset.
    let response = client
        .get_person(with_partition(
            GetPersonRequest {
                team_id: 1,
                person_id: PERSON_ID,
                read_options: None,
            },
            routing_partition,
        ))
        .await
        .unwrap();
    let person = response.into_inner().person.unwrap();
    assert_eq!(person.version, 2);
    let props: serde_json::Value = serde_json::from_slice(&person.properties).unwrap();
    assert_eq!(props["name"], "Recovered");

    cancel.cancel();
}

// ============================================================
// Dirty-index recovery failure: when the changelog fetch cannot
// complete, the person is unavailable — not silently stale
// ============================================================

#[tokio::test]
async fn dirty_person_with_failed_recovery_is_unavailable_not_stale() {
    const PERSON_ID: i64 = 2;
    let routing_partition: u32 = partition_for_person(1, PERSON_ID, NUM_PARTITIONS);
    let (mock_cluster, kafka_producer) = create_test_kafka_with_partitions(4).await;

    let cache = Arc::new(PartitionedCache::new(100));
    let dirty_index = Arc::new(DirtyIndex::new(1_000_000));
    let recovery = test_recovery(&mock_cluster.bootstrap_servers());
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        Arc::clone(&recovery),
    );

    cache.create_partition(routing_partition);
    let person = CachedPerson {
        id: PERSON_ID,
        ..test_cached_person()
    };
    seed_person(&cache, routing_partition, person);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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
    let mut client = create_leader_client(addr).await;

    client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: PERSON_ID,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"name": "Pending"}))
                    .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            routing_partition,
        ))
        .await
        .unwrap();

    let key = PersonCacheKey {
        team_id: 1,
        person_id: PERSON_ID,
    };
    // Point the mark past the HWM so the recovery fetch cannot complete
    // (mark only accepts newer offsets, so bump well beyond the record's).
    let mark = dirty_index.get(&key).unwrap();
    dirty_index.mark(
        key.clone(),
        DirtyMark {
            version: mark.version,
            offset: mark.offset + 1_000,
            partition: mark.partition,
        },
    );
    cache.remove(routing_partition, &key);

    let status = client
        .get_person(with_partition(
            GetPersonRequest {
                team_id: 1,
                person_id: PERSON_ID,
                read_options: None,
            },
            routing_partition,
        ))
        .await
        .unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unavailable);

    cancel.cancel();
}

// ============================================================
// Dirty-index bound: a full index sheds writes for new persons
// rather than acking writes it cannot track
// ============================================================

#[tokio::test]
async fn writes_shed_when_dirty_index_is_full() {
    let partition: u32 = 2;
    let person_a = person_id_for_partition(1, partition);
    let person_b = (person_a + 1..)
        .find(|pid| partition_for_person(1, *pid, NUM_PARTITIONS) == partition)
        .expect("a second person maps to the same partition");

    let (mock_cluster, kafka_producer) = create_test_kafka_with_partitions(4).await;
    let cache = Arc::new(PartitionedCache::new(100));
    // Capacity 1: the first person's mark fills the index.
    let dirty_index = Arc::new(DirtyIndex::new(1));
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        test_recovery(&mock_cluster.bootstrap_servers()),
    );

    cache.create_partition(partition);
    seed_person(
        &cache,
        partition,
        CachedPerson {
            id: person_a,
            ..test_cached_person()
        },
    );
    seed_person(
        &cache,
        partition,
        CachedPerson {
            id: person_b,
            ..test_cached_person()
        },
    );

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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
    let mut client = create_leader_client(addr).await;

    let update_for = |person_id: i64, value: &str| UpdatePersonPropertiesRequest {
        team_id: 1,
        person_id,
        event_name: "$set".to_string(),
        set_properties: serde_json::to_vec(&serde_json::json!({ "k": value })).unwrap(),
        set_once_properties: vec![],
        unset_properties: vec![],
    };

    // First person fills the index.
    client
        .update_person_properties(with_partition(update_for(person_a, "v1"), partition))
        .await
        .expect("first person's write is admitted");

    // The same person stays admitted at capacity — updating its mark does
    // not grow the index.
    client
        .update_person_properties(with_partition(update_for(person_a, "v2"), partition))
        .await
        .expect("marked person's writes stay admitted at capacity");

    // A new person cannot be tracked: the write sheds instead of acking.
    let status = client
        .update_person_properties(with_partition(update_for(person_b, "v1"), partition))
        .await
        .unwrap_err();
    assert_eq!(status.code(), tonic::Code::ResourceExhausted);

    cancel.cancel();
}

// ============================================================
// Recovery version tripwire: a record whose version disagrees
// with the acked mark must fail the read, never be served
// ============================================================

#[tokio::test]
async fn recovery_fails_when_record_version_disagrees_with_the_mark() {
    const PERSON_ID: i64 = 2;
    let routing_partition: u32 = partition_for_person(1, PERSON_ID, NUM_PARTITIONS);
    let (mock_cluster, kafka_producer) = create_test_kafka_with_partitions(4).await;

    let cache = Arc::new(PartitionedCache::new(100));
    let dirty_index = Arc::new(DirtyIndex::new(1_000_000));
    let recovery = test_recovery(&mock_cluster.bootstrap_servers());
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        Arc::clone(&recovery),
    );

    cache.create_partition(routing_partition);
    let person = CachedPerson {
        id: PERSON_ID,
        ..test_cached_person()
    };
    seed_person(&cache, routing_partition, person);

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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
    let mut client = create_leader_client(addr).await;

    client
        .update_person_properties(with_partition(
            UpdatePersonPropertiesRequest {
                team_id: 1,
                person_id: PERSON_ID,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&serde_json::json!({"name": "Tripwire"}))
                    .unwrap(),
                set_once_properties: vec![],
                unset_properties: vec![],
            },
            routing_partition,
        ))
        .await
        .unwrap();

    let key = PersonCacheKey {
        team_id: 1,
        person_id: PERSON_ID,
    };
    // Corrupt the mark's version while keeping the true offset — `mark`
    // only replaces newer offsets, so clear the partition and re-insert.
    // The seek now lands on the right record, but its version disagrees.
    let mark = dirty_index.get(&key).unwrap();
    dirty_index.clear_partition(routing_partition);
    dirty_index.mark(
        key.clone(),
        DirtyMark {
            version: mark.version + 1,
            ..mark
        },
    );
    cache.remove(routing_partition, &key);

    let status = client
        .get_person(with_partition(
            GetPersonRequest {
                team_id: 1,
                person_id: PERSON_ID,
                read_options: None,
            },
            routing_partition,
        ))
        .await
        .unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unavailable);

    cancel.cancel();
}

// ============================================================
// Recovery consumer pooling: repeated recoveries on a partition
// reuse one consumer, repositioning forward and backward
// ============================================================

#[tokio::test]
async fn recovery_reuses_the_partition_consumer_across_fetches() {
    let partition: u32 = 2;
    let person_a = person_id_for_partition(1, partition);
    let person_b = (person_a + 1..)
        .find(|pid| partition_for_person(1, *pid, NUM_PARTITIONS) == partition)
        .expect("a second person maps to the same partition");

    let (mock_cluster, kafka_producer) = create_test_kafka_with_partitions(4).await;
    let cache = Arc::new(PartitionedCache::new(100));
    let dirty_index = Arc::new(DirtyIndex::new(1_000_000));
    let recovery = test_recovery(&mock_cluster.bootstrap_servers());
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        CHANGELOG_TOPIC.to_string(),
        None,
        Arc::new(DashMap::new()),
        Arc::new(InflightTracker::new()),
        NUM_PARTITIONS,
        Arc::clone(&dirty_index),
        Arc::clone(&recovery),
    );

    cache.create_partition(partition);
    for person_id in [person_a, person_b] {
        seed_person(
            &cache,
            partition,
            CachedPerson {
                id: person_id,
                ..test_cached_person()
            },
        );
    }

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cancel = CancellationToken::new();
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
    let client = create_leader_client(addr).await;

    let update_for = |person_id: i64, value: &str| UpdatePersonPropertiesRequest {
        team_id: 1,
        person_id,
        event_name: "$set".to_string(),
        set_properties: serde_json::to_vec(&serde_json::json!({ "who": value })).unwrap(),
        set_once_properties: vec![],
        unset_properties: vec![],
    };
    // A's record lands at offset 0, B's at offset 1.
    for (person_id, value) in [(person_a, "a"), (person_b, "b")] {
        client
            .clone()
            .update_person_properties(with_partition(update_for(person_id, value), partition))
            .await
            .unwrap();
    }

    let recover = |person_id: i64| {
        let mut client = client.clone();
        async move {
            let response = client
                .get_person(with_partition(
                    GetPersonRequest {
                        team_id: 1,
                        person_id,
                        read_options: None,
                    },
                    partition,
                ))
                .await
                .unwrap();
            let person = response.into_inner().person.unwrap();
            let props: serde_json::Value = serde_json::from_slice(&person.properties).unwrap();
            props["who"].as_str().unwrap().to_string()
        }
    };
    let evict = |person_id: i64| {
        cache.remove(
            partition,
            &PersonCacheKey {
                team_id: 1,
                person_id,
            },
        )
    };

    // All three recoveries share the partition's pooled consumer: the
    // first fetches at offset 0, the second repositions forward, and the
    // third repositions backward past a record the consumer already read.
    // A consumer that fails to reposition serves the wrong record (key
    // mismatch) or times out — either fails the unwraps above.
    evict(person_a);
    assert_eq!(recover(person_a).await, "a");
    evict(person_b);
    assert_eq!(recover(person_b).await, "b");
    evict(person_a);
    assert_eq!(recover(person_a).await, "a");

    cancel.cancel();
}

/// A client disconnect mid-recovery drops the request future at an await
/// point. Checkout is an RAII guard, so the cancelled fetch's consumer
/// must come home: without Drop-based return, every cancellation leaked
/// the consumer while freeing its permit, and pool_size cancellations
/// left permits pointing at an empty pool — a panic under the pool mutex
/// that poisoned it and disabled recovery until restart.
#[tokio::test]
async fn cancelled_recovery_returns_its_consumer_to_the_pool() {
    use common::test_kafka_config;
    use personhog_leader::recovery::{ChangelogRecovery, RecoveryConfig};
    use rdkafka::producer::FutureRecord;

    let (mock_cluster, producer) = create_test_kafka().await;
    let mut kafka = test_kafka_config();
    kafka.kafka_hosts = mock_cluster.bootstrap_servers();
    // pool_size 1: a single leaked consumer exhausts the pool.
    let recovery = ChangelogRecovery::new(RecoveryConfig {
        kafka,
        topic: CHANGELOG_TOPIC.to_string(),
        pod_name: "cancel-pod".to_string(),
        recv_timeout: Duration::from_secs(2),
        pool_size: 1,
    })
    .unwrap();

    let key = PersonCacheKey {
        team_id: 1,
        person_id: 7,
    };
    let mark = DirtyMark {
        version: 1,
        offset: 0,
        partition: 0,
    };

    // Nothing is produced yet, so each fetch parks awaiting the record;
    // cancel it mid-park, more times than the pool holds consumers.
    for _ in 0..3 {
        let cancelled = tokio::time::timeout(
            Duration::from_millis(50),
            recovery.fetch_person_at(&mark, &key),
        )
        .await;
        assert!(
            cancelled.is_err(),
            "the fetch must still be parked when cancelled"
        );
    }

    // The pool must still function end to end: produce the sought record
    // and the next fetch — checkout included — succeeds.
    let person = Person {
        id: 7,
        uuid: "00000000-0000-0000-0000-000000000007".to_string(),
        team_id: 1,
        properties: serde_json::to_vec(&serde_json::json!({"k": "v"})).unwrap(),
        properties_last_updated_at: Vec::new(),
        properties_last_operation: Vec::new(),
        created_at: 1_700_000_000,
        version: 1,
        is_identified: false,
        is_user_id: None,
        last_seen_at: None,
    };
    let payload = person.encode_to_vec();
    producer
        .send(
            FutureRecord::to(CHANGELOG_TOPIC)
                .key("1:7")
                .partition(0)
                .payload(&payload),
            Duration::from_secs(5),
        )
        .await
        .expect("produce");

    let recovered = recovery
        .fetch_person_at(&mark, &key)
        .await
        .expect("the pool must survive cancellations");
    assert_eq!(recovered.id, 7);
}
