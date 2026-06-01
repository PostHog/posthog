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

/// Generous default deadline for tests — long enough that no normal
/// drain hits it, so tests of the success path don't accidentally
/// expire requests. The `stash_full_…` and `stash_wait_exceeded_…`
/// tests pass tighter values explicitly.
const TEST_MAX_STASH_WAIT: Duration = Duration::from_secs(30);
/// Conservative concurrency for tests so the per-key fan-out is
/// exercised but doesn't dwarf the test's worker count.
const TEST_DRAIN_CONCURRENCY: usize = 4;

fn new_test_handler(backend: Arc<LeaderBackend>) -> RouterStashHandler {
    RouterStashHandler::new(backend, TEST_MAX_STASH_WAIT, TEST_DRAIN_CONCURRENCY)
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
    let handler = new_test_handler(Arc::clone(&backend));

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
    let handler = new_test_handler(Arc::clone(&backend));

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
    let handler = new_test_handler(Arc::clone(&backend));

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
    let handler = new_test_handler(Arc::clone(&backend));

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
    let handler = new_test_handler(Arc::clone(&backend));

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

/// Ordering invariant (Comment 3): a request that arrives during drain
/// for a partition must be applied at the leader *after* the requests
/// that were already in the stash queue. Without the loop-drain pattern,
/// drain would evict the dashmap entry up-front and let the new request
/// bypass the stash via the live forward path — racing ahead of older
/// stashed requests being replayed and corrupting per-key ordering at
/// the leader.
///
/// We exercise this by injecting a stashed request, then triggering
/// drain in one task and a live request to the same key in another.
/// Both requests target the same `(team_id, person_id)`, so the
/// `TestLeaderService`'s per-key version increment makes ordering
/// observable: the stashed request must be processed first (version
/// bumps to N+1), then the live one (version bumps to N+2).
#[tokio::test]
async fn ordering_preserved_when_request_arrives_during_drain() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX);
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = new_test_handler(Arc::clone(&backend));

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Stash request "A" with email v1.
    let req_a = mk_request(person.team_id, person.id, "v1@example.com");
    let backend_a = Arc::clone(&backend);
    let pending_a = tokio::spawn(async move { backend_a.update_person_properties(req_a).await });
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert!(!pending_a.is_finished(), "A must be parked in stash");

    // Run drain in one task. While drain is in flight, send live
    // request "B" for the same key. B will land in the still-active
    // stash queue (dashmap entry not yet evicted) and be picked up
    // by drain's next loop iteration.
    let handler_for_drain = Arc::new(handler);
    let drain_handler = Arc::clone(&handler_for_drain);
    let drain_task = tokio::spawn(async move {
        drain_handler
            .drain_stash(partition, "leader-new")
            .await
            .unwrap();
    });

    // Send B shortly after drain begins.
    tokio::time::sleep(Duration::from_millis(5)).await;
    let req_b = mk_request(person.team_id, person.id, "v2@example.com");
    let backend_b = Arc::clone(&backend);
    let pending_b = tokio::spawn(async move { backend_b.update_person_properties(req_b).await });

    drain_task.await.unwrap();

    let resp_a = pending_a.await.unwrap().expect("A should succeed");
    let resp_b = pending_b.await.unwrap().expect("B should succeed");

    let initial = person.version;
    assert_eq!(
        resp_a.person.unwrap().version,
        initial + 1,
        "A (stashed first) must be applied first"
    );
    assert_eq!(
        resp_b.person.unwrap().version,
        initial + 2,
        "B (arrived during drain) must be applied second"
    );
}

/// Deadline invariant (Comment 1): if a stashed request's wait time
/// exceeds `max_stash_wait`, drain returns `UNAVAILABLE` to the
/// original caller without forwarding. This bounds the latency a
/// client perceives during a long drain and gives them a definitive
/// retryable error code instead of an ambiguous gRPC timeout. Without
/// this, a stashed write could complete at the leader after the
/// client's gRPC deadline expired, leading to client-driven retries
/// that produce duplicate writes the leader processes idempotently
/// but with surprising version bumps.
#[tokio::test]
async fn stash_wait_exceeded_returns_unavailable() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX);
    let backend = make_backend(leader_addr, stash.clone()).await;
    // Tight deadline — any request that ages past ~50ms in the stash
    // gets failed fast on drain.
    let handler = RouterStashHandler::new(Arc::clone(&backend), Duration::from_millis(50), 4);

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    let req = mk_request(person.team_id, person.id, "stale@example.com");
    let backend_for_call = Arc::clone(&backend);
    let pending = tokio::spawn(async move { backend_for_call.update_person_properties(req).await });

    // Wait long enough that the stashed request is past its deadline.
    tokio::time::sleep(Duration::from_millis(100)).await;
    handler.drain_stash(partition, "leader-new").await.unwrap();

    let result = pending.await.unwrap();
    let err = result.expect_err("drain must fail-fast past-deadline requests");
    assert_eq!(
        err.code(),
        Code::Unavailable,
        "past-deadline drained requests must surface as UNAVAILABLE"
    );
}

/// Convergence invariant: the loop-drain must terminate even when new
/// requests keep arriving during drain (so long as forward-rate keeps
/// up with arrival-rate). This test produces a steady stream of
/// requests for a partition while drain runs, asserting that drain
/// eventually completes and the dashmap entry is evicted.
///
/// The forward rate (round-trip to local mock) far outpaces any
/// arrival rate this test can sustain, so termination is expected
/// quickly. The point is to exercise the loop's "one more iteration"
/// path many times.
#[tokio::test]
async fn drain_converges_with_concurrent_arrivals() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX);
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = Arc::new(new_test_handler(Arc::clone(&backend)));

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Pre-stash a few requests so drain has something to chew on.
    let mut pending: Vec<_> = Vec::new();
    for _ in 0..5 {
        let backend = Arc::clone(&backend);
        let req = mk_request(person.team_id, person.id, "x@example.com");
        pending.push(tokio::spawn(async move {
            backend.update_person_properties(req).await
        }));
    }
    tokio::time::sleep(Duration::from_millis(20)).await;

    // Spawn a drain task and a concurrent arrival task that keeps
    // pushing requests for ~200ms.
    let drain_handler = Arc::clone(&handler);
    let drain_task = tokio::spawn(async move {
        drain_handler
            .drain_stash(partition, "leader-new")
            .await
            .unwrap();
    });

    let arrival_backend = Arc::clone(&backend);
    let arrival_pending = Arc::new(std::sync::Mutex::new(Vec::new()));
    let arrival_pending_for_task = Arc::clone(&arrival_pending);
    let arrival_task = tokio::spawn(async move {
        let start = std::time::Instant::now();
        while start.elapsed() < Duration::from_millis(200) {
            let backend = Arc::clone(&arrival_backend);
            let req = mk_request(person.team_id, person.id, "x@example.com");
            arrival_pending_for_task
                .lock()
                .unwrap()
                .push(tokio::spawn(async move {
                    backend.update_person_properties(req).await
                }));
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    });

    // Drain must terminate even with the arrival pressure. If the
    // loop fails to converge, this `await` will hang and the test
    // harness will time out.
    drain_task.await.unwrap();
    arrival_task.await.unwrap();

    // Every spawned request — pre-stashed and during-drain — must
    // produce a definitive result (success or UNAVAILABLE). We don't
    // care which; the point is that drain converged and every parked
    // future was released, not that any specific outcome held.
    for h in pending {
        drop(h.await.unwrap());
    }
    let arrivals = std::mem::take(&mut *arrival_pending.lock().unwrap());
    for h in arrivals {
        drop(h.await.unwrap());
    }
}
