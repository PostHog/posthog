mod common;

use std::sync::Arc;

use common::{
    create_leader_client, seed_person, start_coordinator, start_leader_pod,
    start_leader_pod_with_lease_ttl, start_router, test_cached_person, test_store,
    wait_for_condition, NUM_PARTITIONS, POLL_INTERVAL, WAIT_TIMEOUT,
};
use personhog_coordination::strategy::StickyBalancedStrategy;
use personhog_leader::cache::PartitionedCache;
use personhog_leader::service::PersonHogLeaderService;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use personhog_proto::personhog::leader::v1::{
    LeaderGetPersonRequest, UpdatePersonPropertiesRequest,
};
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use tonic::transport::Server;

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
        .get_person(LeaderGetPersonRequest {
            team_id: 1,
            person_id: 42,
            partition: 0,
        })
        .await
        .unwrap();

    let proto_person = response.into_inner().person.unwrap();
    assert_eq!(proto_person.id, 42);
    assert_eq!(proto_person.team_id, 1);

    // Update should succeed
    let response = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({"name": "Updated"})).unwrap(),
            set_once_properties: vec![],
            unset_properties: vec![],
            partition: 0,
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);
    assert_eq!(result.person.unwrap().version, 2);

    // Read back should reflect the update
    let response = client
        .get_person(LeaderGetPersonRequest {
            team_id: 1,
            person_id: 42,
            partition: 0,
        })
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
    let service = PersonHogLeaderService::new(Arc::clone(&cache));

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
    let result = client
        .get_person(LeaderGetPersonRequest {
            team_id: 1,
            person_id: 42,
            partition: 0,
        })
        .await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::FailedPrecondition);

    // Write to unowned partition → FailedPrecondition
    let result = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: vec![],
            set_once_properties: vec![],
            unset_properties: vec![],
            partition: 0,
        })
        .await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::FailedPrecondition);

    // Manually warm partition → now NotFound (partition exists, no data)
    cache.create_partition(0);

    let result = client
        .get_person(LeaderGetPersonRequest {
            team_id: 1,
            person_id: 42,
            partition: 0,
        })
        .await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::NotFound);

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
        .get_person(LeaderGetPersonRequest {
            team_id: 1,
            person_id: 42,
            partition: 0,
        })
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

    // Pod 1: released partition → FailedPrecondition
    let result = client1
        .get_person(LeaderGetPersonRequest {
            team_id: 1,
            person_id: 42,
            partition: moved_partition,
        })
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
        .get_person(LeaderGetPersonRequest {
            team_id: 1,
            person_id: 42,
            partition: moved_partition,
        })
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
    let result = client2
        .get_person(LeaderGetPersonRequest {
            team_id: 1,
            person_id: 42,
            partition: 0,
        })
        .await;
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::NotFound);

    cancel.cancel();
}
