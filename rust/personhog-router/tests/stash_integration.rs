//! Integration tests for the stash data path. Wires a real `LeaderBackend`,
//! a real `StashTable`, and a real `RouterStashHandler` against an in-process
//! `TestLeaderService`. Exercises the full request → stash → drain → reply
//! lifecycle that production runs through during a partition handoff,
//! catching wiring regressions that the per-component unit tests can't.

mod common;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common::{create_test_person, start_test_leader, TestLeaderService};
use personhog_coordination::routing_table::StashHandler;
use personhog_proto::personhog::types::v1::UpdatePersonPropertiesRequest;
use personhog_router::backend::{LeaderBackend, LeaderBackendConfig, LeaderOps, StashTable};
use personhog_router::config::RetryConfig;
use personhog_router::stash_handler::RouterStashHandler;
use tokio::sync::RwLock;
use tonic::Code;

const NUM_PARTITIONS: u32 = 8;

fn retry_config() -> RetryConfig {
    RetryConfig {
        max_retries: 0,
        initial_backoff_ms: 1,
        max_backoff_ms: 1,
    }
}

/// Build a `LeaderBackend` whose routing table maps every partition at the
/// given `leader_addr` and whose stash uses the supplied bounds.
async fn make_backend(leader_addr: std::net::SocketAddr, stash: StashTable) -> Arc<LeaderBackend> {
    let routing_table = Arc::new(RwLock::new(HashMap::new()));
    {
        let mut table = routing_table.write().await;
        for partition in 0..NUM_PARTITIONS {
            table.insert(partition, "leader-0".to_string());
        }
    }
    let leader_url = format!("http://{}", leader_addr);
    let resolver: personhog_router::backend::AddressResolver = Arc::new({
        let url = leader_url.clone();
        move |_pod: &str| Some(url.clone())
    });

    Arc::new(LeaderBackend::new(
        routing_table,
        resolver,
        LeaderBackendConfig {
            num_partitions: NUM_PARTITIONS,
            timeout: Duration::from_secs(5),
            retry_config: retry_config(),
            max_send_message_size: 4 * 1024 * 1024,
            max_recv_message_size: 4 * 1024 * 1024,
        },
        stash,
    ))
}

fn mk_request(team_id: i64, person_id: i64, set_email: &str) -> UpdatePersonPropertiesRequest {
    UpdatePersonPropertiesRequest {
        team_id,
        person_id,
        partition: 0, // overwritten by LeaderBackend::update_person_properties
        event_name: "test".to_string(),
        set_properties: serde_json::to_vec(&serde_json::json!({ "email": set_email })).unwrap(),
        set_once_properties: Vec::new(),
        unset_properties: Vec::new(),
    }
}

/// A request that arrives while the stash is open must park on a oneshot,
/// and a subsequent `drain_stash` must forward it to the leader and deliver
/// the leader's reply back to the original caller. This is the core contract
/// the entire stash data path is built around.
#[tokio::test]
async fn request_during_stash_completes_after_drain() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX);
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = RouterStashHandler::new(Arc::clone(&backend));

    // Open the stash for the partition this request will land on.
    let partition = backend.partition_for_person(person.team_id, person.id);
    handler
        .begin_stash(partition, "leader-new")
        .await
        .expect("begin_stash should succeed");

    // Send the write. It should park inside the LeaderBackend's stash hook.
    let req = mk_request(person.team_id, person.id, "stashed@example.com");
    let backend_for_call = Arc::clone(&backend);
    let in_flight =
        tokio::spawn(async move { backend_for_call.update_person_properties(req).await });

    // Briefly wait so the in-flight request actually parked in the stash.
    tokio::time::sleep(Duration::from_millis(50)).await;
    assert!(
        !in_flight.is_finished(),
        "request must be parked in the stash, not forwarded yet"
    );

    // Drain. The handler forwards the buffered request via the unified
    // routing path, awaits the leader's reply, then sends it through the
    // oneshot back to the original caller.
    handler
        .drain_stash(partition, "leader-new")
        .await
        .expect("drain_stash should succeed");

    let response = tokio::time::timeout(Duration::from_secs(2), in_flight)
        .await
        .expect("drain should release the parked request promptly")
        .expect("task should not panic")
        .expect("update should succeed");
    let returned = response.person.expect("leader returned a person");
    assert_eq!(returned.id, person.id);
    assert!(response.updated, "leader marked the update as applied");
}

/// Multiple requests stashed for the same partition must drain in FIFO
/// order and each must receive its leader reply via its own oneshot.
#[tokio::test]
async fn multiple_stashed_requests_drain_in_fifo() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX);
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = RouterStashHandler::new(Arc::clone(&backend));

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Park three updates with distinct payloads. The TestLeaderService
    // increments the person's version on every call, so the response
    // version doubles as a sequence number.
    let mut joins = Vec::new();
    for i in 0..3 {
        let backend = Arc::clone(&backend);
        let req = mk_request(person.team_id, person.id, &format!("v{i}@example.com"));
        joins.push(tokio::spawn(async move {
            backend.update_person_properties(req).await
        }));
    }

    tokio::time::sleep(Duration::from_millis(50)).await;
    for j in &joins {
        assert!(!j.is_finished(), "all three should still be parked");
    }

    handler.drain_stash(partition, "leader-new").await.unwrap();

    // Collect responses in spawn order. The drain forwards in FIFO order,
    // so version increments must be monotonic relative to spawn order
    // (1, 2, 3) — proving FIFO is preserved end to end.
    let mut versions = Vec::with_capacity(3);
    for j in joins {
        let resp = tokio::time::timeout(Duration::from_secs(2), j)
            .await
            .expect("each parked request should release after drain")
            .expect("task should not panic")
            .expect("update should succeed");
        versions.push(resp.person.unwrap().version);
    }

    let initial = person.version;
    assert_eq!(
        versions,
        vec![initial + 1, initial + 2, initial + 3],
        "stashed requests must drain in FIFO order"
    );
}

/// Requests for partitions that aren't stashed must flow through to the
/// leader unchanged. Proves the stash hook is partition-scoped and doesn't
/// interfere with normal traffic during a handoff for some other partition.
#[tokio::test]
async fn requests_for_unstashed_partition_forward_immediately() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX);
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = RouterStashHandler::new(Arc::clone(&backend));

    // Stash a partition that isn't ours, then send a request for our
    // partition. It should not park.
    let our_partition = backend.partition_for_person(person.team_id, person.id);
    let other_partition = (our_partition + 1) % NUM_PARTITIONS;
    handler
        .begin_stash(other_partition, "leader-new")
        .await
        .unwrap();

    let req = mk_request(person.team_id, person.id, "live@example.com");
    let result = tokio::time::timeout(
        Duration::from_secs(2),
        backend.update_person_properties(req),
    )
    .await
    .expect("forward should not block");
    let response = result.expect("update should succeed");
    assert!(response.updated);
}

/// Once the stash for a partition is full, additional writes return
/// `UNAVAILABLE` so callers can retry. Verified end to end through the
/// `LeaderBackend` (the unit test covers the same path via direct call).
#[tokio::test]
async fn stash_full_returns_unavailable_via_backend() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    // Tight cap: only one stashed message per partition.
    let stash = StashTable::with_bounds(1, usize::MAX);
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = RouterStashHandler::new(Arc::clone(&backend));

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Park the first request.
    let req1 = mk_request(person.team_id, person.id, "first@example.com");
    let backend1 = Arc::clone(&backend);
    let _in_flight = tokio::spawn(async move { backend1.update_person_properties(req1).await });
    tokio::time::sleep(Duration::from_millis(50)).await;

    // The second request hits the cap and is rejected.
    let req2 = mk_request(person.team_id, person.id, "second@example.com");
    let err = backend
        .update_person_properties(req2)
        .await
        .expect_err("second request must be rejected");
    assert_eq!(
        err.code(),
        Code::Unavailable,
        "rejection must surface as UNAVAILABLE so callers retry"
    );
}

/// Begin → drain → begin again on the same partition must produce a fresh
/// queue. After a Complete-driven drain, a subsequent handoff for the same
/// partition (typically a back-to-back rebalance) must buffer fresh writes,
/// not bleed state from the prior handoff.
#[tokio::test]
async fn back_to_back_handoffs_use_fresh_queue() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX);
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = RouterStashHandler::new(Arc::clone(&backend));

    let partition = backend.partition_for_person(person.team_id, person.id);

    // First handoff cycle.
    handler.begin_stash(partition, "leader-a").await.unwrap();
    let req_a = mk_request(person.team_id, person.id, "a@example.com");
    let backend_a = Arc::clone(&backend);
    let pending_a = tokio::spawn(async move { backend_a.update_person_properties(req_a).await });
    tokio::time::sleep(Duration::from_millis(20)).await;
    handler.drain_stash(partition, "leader-a").await.unwrap();
    pending_a
        .await
        .unwrap()
        .expect("first handoff's stashed request should drain successfully");

    // Second handoff cycle on the same partition. Must accept a new write
    // (proving the partition is back to a stashable state) and drain it
    // independently.
    handler.begin_stash(partition, "leader-b").await.unwrap();
    let req_b = mk_request(person.team_id, person.id, "b@example.com");
    let backend_b = Arc::clone(&backend);
    let pending_b = tokio::spawn(async move { backend_b.update_person_properties(req_b).await });
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert!(
        !pending_b.is_finished(),
        "second handoff's request must park, not forward"
    );
    handler.drain_stash(partition, "leader-b").await.unwrap();
    pending_b
        .await
        .unwrap()
        .expect("second handoff's stashed request should drain successfully");
}
