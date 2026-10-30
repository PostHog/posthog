//! Integration tests for the stash data path. Wires a real `LeaderBackend`,
//! a real `StashTable`, and a real `RouterStashHandler` against an in-process
//! `TestLeaderService`. Exercises the full request → stash → drain → reply
//! lifecycle that production runs through during a partition handoff,
//! catching wiring regressions that the per-component unit tests can't.

mod common;

use std::collections::HashMap;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use bytes::Bytes;
use common::{create_test_person, start_test_leader, start_test_leader_at, TestLeaderService};
use http::HeaderMap;
use http_body_util::BodyExt;
use personhog_common::partitioning::partition_for_person;
use personhog_coordination::changelog::LiveChangelog;
use personhog_coordination::routing_table::StashHandler;
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::{ChangelogConfig, Generation};
use personhog_proto::personhog::types::v1::{
    FoldPersonDocumentRequest, FoldPersonDocumentResponse, GetPersonRequest, GetPersonResponse,
    Person, SealedSourceSnapshot, UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use personhog_router::backend::{LeaderBackend, LeaderBackendConfig, StashTable};
use personhog_router::config::Http2Windows;
use personhog_router::stash_handler::RouterStashHandler;
use prost::Message;
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;
use tonic::body::BoxBody;
use tonic::Code;

const NUM_PARTITIONS: u32 = 8;

/// Generous default deadline for tests — long enough that no normal
/// drain hits it, so tests of the success path don't accidentally
/// expire requests. The `stash_full_…` and `stash_wait_exceeded_…`
/// tests pass tighter values explicitly.
const TEST_MAX_STASH_WAIT: Duration = Duration::from_secs(30);
/// Conservative concurrency for tests so the per-key fan-out is
/// exercised but doesn't dwarf the test's worker count.
const TEST_DRAIN_CONCURRENCY: usize = 4;

async fn new_test_handler(backend: Arc<LeaderBackend>) -> RouterStashHandler {
    RouterStashHandler::new(
        backend,
        TEST_MAX_STASH_WAIT,
        TEST_DRAIN_CONCURRENCY,
        test_store().await,
    )
}

/// A store under a fresh prefix: a drain's config read finds nothing and keeps the backend's.
async fn test_store() -> Arc<PersonhogStore> {
    let inner = EtcdStore::connect(StoreConfig {
        endpoints: vec!["http://localhost:2379".to_string()],
        prefix: format!("/stash-test-{}/", rand::random::<u64>()),
    })
    .await
    .expect("failed to connect to etcd");
    Arc::new(PersonhogStore::new(inner))
}

fn changelog() -> LiveChangelog {
    LiveChangelog::new(ChangelogConfig::new("personhog_updates", NUM_PARTITIONS))
}

/// Build a `LeaderBackend` whose routing table maps every partition at the
/// given `leader_addr` and whose stash uses the supplied bounds.
async fn make_backend(leader_addr: std::net::SocketAddr, stash: StashTable) -> Arc<LeaderBackend> {
    backend_with(leader_addr, changelog(), stash, NUM_PARTITIONS).await
}

/// A backend routing partitions `0..routed` to `leader_addr`, reading the count from `changelog`.
async fn backend_with(
    leader_addr: std::net::SocketAddr,
    changelog: LiveChangelog,
    stash: StashTable,
    routed: u32,
) -> Arc<LeaderBackend> {
    let routing_table = Arc::new(RwLock::new(HashMap::new()));
    {
        let mut table = routing_table.write().await;
        for partition in 0..routed {
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
            changelog,
            timeout: Duration::from_secs(5),
            num_channels: 1,
            http2_windows: Http2Windows::default(),
        },
        stash,
    ))
}

fn mk_request(team_id: i64, person_id: i64, set_email: &str) -> UpdatePersonPropertiesRequest {
    UpdatePersonPropertiesRequest {
        force_update: false,
        team_id,
        person_id,
        event_name: "test".to_string(),
        set_properties: serde_json::to_vec(&serde_json::json!({ "email": set_email })).unwrap(),
        set_once_properties: Vec::new(),
        unset_properties: Vec::new(),
        is_identified: None,
        last_seen_at: None,
    }
}

/// Encode a typed request into a gRPC length-prefixed frame, as a client
/// would send it over the wire.
fn encode_frame<T: Message>(req: &T) -> Bytes {
    let encoded = req.encode_to_vec();
    let mut buf = Vec::with_capacity(5 + encoded.len());
    buf.push(0); // not compressed
    buf.extend_from_slice(&(encoded.len() as u32).to_be_bytes());
    buf.extend(encoded);
    Bytes::from(buf)
}

/// Drive a write through the backend's raw, stash-aware forward path,
/// returning the router's gRPC response.
async fn forward(
    backend: &LeaderBackend,
    req: UpdatePersonPropertiesRequest,
) -> http::Response<BoxBody> {
    let key = (req.team_id, req.person_id);
    let (response, _call_ms) = backend
        .forward_or_stash(
            "UpdatePersonProperties",
            key,
            HeaderMap::new(),
            encode_frame(&req),
        )
        .await;
    response
}

/// Decode a router response into the typed leader response on success, or
/// its gRPC status code on error. The status lives in the response headers
/// (router-generated errors, trailers-only leader errors) or the trailers
/// (a normal leader response).
async fn decode_response<T: Message + Default>(resp: http::Response<BoxBody>) -> Result<T, Code> {
    let (parts, body) = resp.into_parts();
    let collected = body.collect().await.expect("collect leader response body");
    let trailers = collected.trailers().cloned();
    let data = collected.to_bytes();

    let status = parts
        .headers
        .get("grpc-status")
        .or_else(|| trailers.as_ref().and_then(|t| t.get("grpc-status")))
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<i32>().ok())
        .unwrap_or(0);
    if status != 0 {
        return Err(Code::from(status));
    }

    let msg = data
        .get(5..)
        .expect("successful response carries a gRPC frame");
    Ok(T::decode(msg).expect("decode leader response message"))
}

/// Drive a strong read through the backend's raw, stash-aware forward
/// path — the same route `raw_proxy_to_leader` takes for a strong
/// `GetPerson` — returning the router's gRPC response.
async fn forward_read(
    backend: &LeaderBackend,
    team_id: i64,
    person_id: i64,
) -> http::Response<BoxBody> {
    let req = GetPersonRequest {
        team_id,
        person_id,
        read_options: None,
    };
    let encoded = req.encode_to_vec();
    let mut buf = Vec::with_capacity(5 + encoded.len());
    buf.push(0);
    buf.extend_from_slice(&(encoded.len() as u32).to_be_bytes());
    buf.extend(encoded);

    let (response, _call_ms) = backend
        .forward_or_stash(
            "GetPerson",
            (team_id, person_id),
            HeaderMap::new(),
            Bytes::from(buf),
        )
        .await;
    response
}

/// A partition born in the flip has no owner until its fresh handoff lands;
/// a write for it parks and drains with that handoff instead of bouncing.
#[tokio::test]
async fn a_write_for_a_partition_born_in_the_flip_parks_until_its_handoff_drains() {
    born_partition_write_parks(false).await;
}

/// The retire can reach a router before the born partition's route does; the
/// write still parks rather than bouncing.
#[tokio::test]
async fn a_born_partition_write_parks_when_the_retire_lands_before_its_route() {
    born_partition_write_parks(true).await;
}

async fn born_partition_write_parks(retired_first: bool) {
    let old_count = NUM_PARTITIONS / 2;
    let team_id = 1;
    let person_id = (1..)
        .find(|id| partition_for_person(team_id, *id, NUM_PARTITIONS) >= old_count)
        .expect("some key lands in the new space");
    let partition = partition_for_person(team_id, person_id, NUM_PARTITIONS);
    let person = Person {
        id: person_id,
        team_id,
        ..create_test_person()
    };
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person)).await;

    let routing_table = Arc::new(RwLock::new(HashMap::new()));
    for owned in 0..old_count {
        routing_table
            .write()
            .await
            .insert(owned, "leader-0".to_string());
    }
    let changelog = LiveChangelog::new(ChangelogConfig {
        topic: "personhog_updates_v2".to_string(),
        partitions: NUM_PARTITIONS,
        epoch: 2,
        writer_group: String::new(),
        retire_groups: vec![],
        draining: vec![Generation {
            topic: "personhog_updates_v1".to_string(),
            partitions: old_count,
            epoch: 1,
        }],
    })
    .holding_floor();
    if retired_first {
        let mut retired = changelog.current();
        retired.draining.clear();
        assert!(changelog.adopt(&retired));
    }
    let leader_url = format!("http://{leader_addr}");
    let resolver: personhog_router::backend::AddressResolver =
        Arc::new(move |_pod: &str| Some(leader_url.clone()));
    let backend = Arc::new(LeaderBackend::new(
        Arc::clone(&routing_table),
        resolver,
        LeaderBackendConfig {
            changelog: changelog.clone(),
            timeout: Duration::from_secs(5),
            num_channels: 1,
            http2_windows: Http2Windows::default(),
        },
        StashTable::with_bounds(usize::MAX, usize::MAX, changelog.clone()),
    ));
    let handler = new_test_handler(Arc::clone(&backend)).await;

    let req = mk_request(team_id, person_id, "born@example.com");
    let backend_for_call = Arc::clone(&backend);
    let in_flight = tokio::spawn(async move { forward(&backend_for_call, req).await });
    let parked = tokio::time::timeout(Duration::from_secs(2), async {
        while !handler.stash_pending(partition) {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await;
    assert!(parked.is_ok(), "the write parks instead of bouncing");
    assert!(!in_flight.is_finished());

    // The fresh handoff lands and completes.
    routing_table
        .write()
        .await
        .insert(partition, "leader-0".to_string());
    handler
        .drain_stash(partition, "leader-0", CancellationToken::new())
        .await
        .expect("drain_stash should succeed");

    let raw = tokio::time::timeout(Duration::from_secs(2), in_flight)
        .await
        .expect("the drain releases the parked write")
        .expect("task should not panic");
    let response = decode_response::<UpdatePersonPropertiesResponse>(raw)
        .await
        .expect("the write succeeds once its partition has an owner");
    assert_eq!(response.person.expect("a person").id, person_id);

    if retired_first {
        // Once every born partition has a route, the next write drops the held floor.
        for born in old_count..NUM_PARTITIONS {
            routing_table
                .write()
                .await
                .insert(born, "leader-0".to_string());
        }
        assert_eq!(changelog.draining_floor(), Some(old_count));
        forward(
            &backend,
            mk_request(team_id, person_id, "after@example.com"),
        )
        .await;
        assert_eq!(changelog.draining_floor(), None);
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

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = new_test_handler(Arc::clone(&backend)).await;

    // Open the stash for the partition this request will land on.
    let partition = backend.partition_for_person(person.team_id, person.id);
    handler
        .begin_stash(partition, "leader-new")
        .await
        .expect("begin_stash should succeed");

    // Send the write. It should park inside the LeaderBackend's stash hook.
    let req = mk_request(person.team_id, person.id, "stashed@example.com");
    let backend_for_call = Arc::clone(&backend);
    let in_flight = tokio::spawn(async move { forward(&backend_for_call, req).await });

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
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .expect("drain_stash should succeed");

    let raw = tokio::time::timeout(Duration::from_secs(2), in_flight)
        .await
        .expect("drain should release the parked request promptly")
        .expect("task should not panic");
    let response = decode_response::<UpdatePersonPropertiesResponse>(raw)
        .await
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

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = new_test_handler(Arc::clone(&backend)).await;

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Park three updates with distinct payloads. The TestLeaderService
    // increments the person's version on every call, so the response
    // version doubles as a sequence number.
    let mut joins = Vec::new();
    for i in 0..3 {
        let backend = Arc::clone(&backend);
        let req = mk_request(person.team_id, person.id, &format!("v{i}@example.com"));
        joins.push(tokio::spawn(async move { forward(&backend, req).await }));
    }

    tokio::time::sleep(Duration::from_millis(50)).await;
    for j in &joins {
        assert!(!j.is_finished(), "all three should still be parked");
    }

    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();

    // Collect responses in spawn order. The drain forwards in FIFO order,
    // so version increments must be monotonic relative to spawn order
    // (1, 2, 3) — proving FIFO is preserved end to end.
    let mut versions = Vec::with_capacity(3);
    for j in joins {
        let raw = tokio::time::timeout(Duration::from_secs(2), j)
            .await
            .expect("each parked request should release after drain")
            .expect("task should not panic");
        let resp = decode_response::<UpdatePersonPropertiesResponse>(raw)
            .await
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

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = new_test_handler(Arc::clone(&backend)).await;

    // Stash a partition that isn't ours, then send a request for our
    // partition. It should not park.
    let our_partition = backend.partition_for_person(person.team_id, person.id);
    let other_partition = (our_partition + 1) % NUM_PARTITIONS;
    handler
        .begin_stash(other_partition, "leader-new")
        .await
        .unwrap();

    let req = mk_request(person.team_id, person.id, "live@example.com");
    let raw = tokio::time::timeout(Duration::from_secs(2), forward(&backend, req))
        .await
        .expect("forward should not block");
    let response = decode_response::<UpdatePersonPropertiesResponse>(raw)
        .await
        .expect("update should succeed");
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
    let stash = StashTable::with_bounds(1, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = new_test_handler(Arc::clone(&backend)).await;

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Park the first request.
    let req1 = mk_request(person.team_id, person.id, "first@example.com");
    let backend1 = Arc::clone(&backend);
    let _in_flight = tokio::spawn(async move { forward(&backend1, req1).await });
    tokio::time::sleep(Duration::from_millis(50)).await;

    // The second request hits the cap and is rejected.
    let req2 = mk_request(person.team_id, person.id, "second@example.com");
    let raw = forward(&backend, req2).await;
    let code = decode_response::<UpdatePersonPropertiesResponse>(raw)
        .await
        .expect_err("second request must be rejected");
    assert_eq!(
        code,
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

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = new_test_handler(Arc::clone(&backend)).await;

    let partition = backend.partition_for_person(person.team_id, person.id);

    // First handoff cycle.
    handler.begin_stash(partition, "leader-a").await.unwrap();
    let req_a = mk_request(person.team_id, person.id, "a@example.com");
    let backend_a = Arc::clone(&backend);
    let pending_a = tokio::spawn(async move { forward(&backend_a, req_a).await });
    tokio::time::sleep(Duration::from_millis(20)).await;
    handler
        .drain_stash(partition, "leader-a", CancellationToken::new())
        .await
        .unwrap();
    let raw_a = pending_a.await.unwrap();
    decode_response::<UpdatePersonPropertiesResponse>(raw_a)
        .await
        .expect("first handoff's stashed request should drain successfully");

    // Second handoff cycle on the same partition. Must accept a new write
    // (proving the partition is back to a stashable state) and drain it
    // independently.
    handler.begin_stash(partition, "leader-b").await.unwrap();
    let req_b = mk_request(person.team_id, person.id, "b@example.com");
    let backend_b = Arc::clone(&backend);
    let pending_b = tokio::spawn(async move { forward(&backend_b, req_b).await });
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert!(
        !pending_b.is_finished(),
        "second handoff's request must park, not forward"
    );
    handler
        .drain_stash(partition, "leader-b", CancellationToken::new())
        .await
        .unwrap();
    let raw_b = pending_b.await.unwrap();
    decode_response::<UpdatePersonPropertiesResponse>(raw_b)
        .await
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

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = new_test_handler(Arc::clone(&backend)).await;

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Stash request "A" with email v1.
    let req_a = mk_request(person.team_id, person.id, "v1@example.com");
    let backend_a = Arc::clone(&backend);
    let pending_a = tokio::spawn(async move { forward(&backend_a, req_a).await });
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
            .drain_stash(partition, "leader-new", CancellationToken::new())
            .await
            .unwrap();
    });

    // Send B shortly after drain begins.
    tokio::time::sleep(Duration::from_millis(5)).await;
    let req_b = mk_request(person.team_id, person.id, "v2@example.com");
    let backend_b = Arc::clone(&backend);
    let pending_b = tokio::spawn(async move { forward(&backend_b, req_b).await });

    drain_task.await.unwrap();

    let resp_a = decode_response::<UpdatePersonPropertiesResponse>(pending_a.await.unwrap())
        .await
        .expect("A should succeed");
    let resp_b = decode_response::<UpdatePersonPropertiesResponse>(pending_b.await.unwrap())
        .await
        .expect("B should succeed");

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

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    // Tight deadline — any request that ages past ~50ms in the stash
    // gets failed fast on drain.
    let handler = RouterStashHandler::new(
        Arc::clone(&backend),
        Duration::from_millis(50),
        4,
        test_store().await,
    );

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    let req = mk_request(person.team_id, person.id, "stale@example.com");
    let backend_for_call = Arc::clone(&backend);
    let pending = tokio::spawn(async move { forward(&backend_for_call, req).await });

    // Wait long enough that the stashed request is past its deadline.
    tokio::time::sleep(Duration::from_millis(100)).await;
    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();

    let raw = pending.await.unwrap();
    let code = decode_response::<UpdatePersonPropertiesResponse>(raw)
        .await
        .expect_err("drain must fail-fast past-deadline requests");
    assert_eq!(
        code,
        Code::Unavailable,
        "past-deadline drained requests must surface as UNAVAILABLE"
    );
}

/// A semantic refusal — the leader's fail-closed verification rejection,
/// FAILED_PRECONDITION marked by metadata — is a final answer, not a
/// routing race: the router must deliver it to the caller unchanged
/// instead of bouncing it into a retriable UNAVAILABLE the saga would
/// loop on forever.
#[tokio::test]
async fn a_semantic_refusal_passes_through_instead_of_bouncing() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;
    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash).await;

    let req = FoldPersonDocumentRequest {
        team_id: person.team_id,
        person_id: person.id,
        sealed_snapshots: vec![SealedSourceSnapshot {
            person: Some(Person::default()),
            ordinal: 0,
        }],
        event_set: b"{}".to_vec(),
        event_set_once: b"{}".to_vec(),
        op_id: "0192b4a0-0000-7000-8000-000000000000".to_string(),
    };
    let (response, _call_ms) = backend
        .forward_or_stash(
            "FoldPersonDocument",
            (person.team_id, person.id),
            HeaderMap::new(),
            encode_frame(&req),
        )
        .await;
    let code = decode_response::<FoldPersonDocumentResponse>(response)
        .await
        .expect_err("the refusal must surface as an error");
    assert_eq!(
        code,
        Code::FailedPrecondition,
        "a marked refusal is delivered, not bounced into UNAVAILABLE"
    );
}

/// A drain that races the target leader's fence (a reaffirm's drain-back
/// arriving before the owner's resume, or a completion's drain hitting a
/// pod mid-cutover) gets FailedPrecondition from the leader — a
/// condition that clears in watch-propagation time. The bounce must be
/// invisible to the client: the request stays parked (no error escapes),
/// the drain eventually yields its lane, and a later drain — the
/// reconcile pass re-requests one every tick — delivers the write once
/// the fence clears.
#[tokio::test]
async fn fence_bounce_parks_requests_until_a_later_drain_delivers() {
    let person = create_test_person();
    let service = TestLeaderService::new()
        .with_person(person.clone())
        .fenced();
    let fence = service.fence_flag();
    let leader_addr = start_test_leader(service).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    // Generous deadline so the deadline path can never produce a client
    // error and mask a bounce that wrongly surfaced one.
    let handler = RouterStashHandler::new(
        Arc::clone(&backend),
        Duration::from_secs(60),
        4,
        test_store().await,
    );

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    let req = mk_request(person.team_id, person.id, "fenced@example.com");
    let backend_for_call = Arc::clone(&backend);
    let pending = tokio::spawn(async move { forward(&backend_for_call, req).await });
    // Let the request park before draining, so the drain can't settle an
    // empty queue and evict the entry before the request arrives.
    tokio::time::sleep(Duration::from_millis(50)).await;

    // First drain: every wave bounces, so the drain backs off, retries,
    // and yields its lane with the request still parked.
    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();
    assert!(
        !pending.is_finished(),
        "a fence bounce must not surface any outcome to the client"
    );

    // The fence clears; the next requested drain (the reconcile pass
    // re-requests one every tick in production) delivers the write.
    fence.store(false, Ordering::SeqCst);
    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();

    let response = pending.await.unwrap();
    decode_response::<UpdatePersonPropertiesResponse>(response)
        .await
        .expect("the post-fence drain must deliver the parked write");
}

/// A transport failure during drain — the target unreachable once the
/// backend's own transient retries are exhausted — must bounce, not
/// fail the client: the request may or may not have reached the leader,
/// and the idempotency contract makes replaying it safe, while erroring
/// would push that ambiguity onto the client. The drain yields with the
/// request parked; once the target is dialable, a later drain replays
/// and delivers it.
#[tokio::test]
async fn transport_failure_parks_requests_until_a_later_drain_delivers() {
    let person = create_test_person();
    // Reserve an address with nothing listening on it, so dials fail at
    // the transport layer (connection refused) until the leader starts.
    let reserved = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let leader_addr = reserved.local_addr().unwrap();
    drop(reserved);

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    // Generous deadline so the deadline path can never produce a client
    // error and mask a bounce that wrongly surfaced one.
    let handler = RouterStashHandler::new(
        Arc::clone(&backend),
        Duration::from_secs(60),
        4,
        test_store().await,
    );

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    let req = mk_request(person.team_id, person.id, "transport@example.com");
    let backend_for_call = Arc::clone(&backend);
    let pending = tokio::spawn(async move { forward(&backend_for_call, req).await });
    // Let the request park before draining, so the drain can't settle an
    // empty queue and evict the entry before the request arrives.
    tokio::time::sleep(Duration::from_millis(50)).await;

    // First drain: every wave fails at the transport layer, so the
    // drain bounces, backs off, and yields with the request parked.
    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();
    assert!(
        !pending.is_finished(),
        "a transport bounce must not surface any outcome to the client"
    );

    // The leader comes up on the reserved address; the next requested
    // drain (the reconcile pass re-requests one every tick in
    // production) replays and delivers.
    start_test_leader_at(
        leader_addr,
        TestLeaderService::new().with_person(person.clone()),
    )
    .await;
    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();

    let response = pending.await.unwrap();
    decode_response::<UpdatePersonPropertiesResponse>(response)
        .await
        .expect("the post-recovery drain must deliver the parked write");
}

/// The live path's re-entrant retry: a write that races a fence — no
/// stash open, the leader still settling — is held by the router and
/// re-attempted, so the client sees a slow success instead of a
/// `FAILED_PRECONDITION` it would not retry.
#[tokio::test]
async fn a_live_write_rides_out_a_fence_via_router_retry() {
    let person = create_test_person();
    let service = TestLeaderService::new()
        .with_person(person.clone())
        .fenced();
    let fence = service.fence_flag();
    let leader_addr = start_test_leader(service).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;

    // The fence clears mid-retry, as it does in production once the
    // pod's watch delivers the phase change.
    tokio::spawn({
        let fence = Arc::clone(&fence);
        async move {
            tokio::time::sleep(Duration::from_millis(200)).await;
            fence.store(false, Ordering::SeqCst);
        }
    });

    let req = mk_request(person.team_id, person.id, "live-fence@example.com");
    let response = forward(&backend, req).await;
    decode_response::<UpdatePersonPropertiesResponse>(response)
        .await
        .expect("the router's retry must absorb the fence and deliver the write");
}

/// A router whose view never updates (the fence never clears from its
/// perspective) must not hold requests forever: the bounce budget runs
/// out and the client gets a retryable `UNAVAILABLE` — never the
/// `FAILED_PRECONDITION` the leader actually answered with, which
/// clients read as "do not retry".
#[tokio::test]
async fn a_live_write_past_the_bounce_budget_fails_unavailable() {
    let person = create_test_person();
    let leader_addr = start_test_leader(
        TestLeaderService::new()
            .with_person(person.clone())
            .fenced(),
    )
    .await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;

    let req = mk_request(person.team_id, person.id, "live-wedged@example.com");
    let response = forward(&backend, req).await;
    let code = decode_response::<UpdatePersonPropertiesResponse>(response)
        .await
        .expect_err("a persistently fenced target must fail the write");
    assert_eq!(
        code,
        Code::Unavailable,
        "bounce-budget exhaustion must surface as retryable UNAVAILABLE, never FAILED_PRECONDITION"
    );
}

/// The unified loop's marquee behavior: a live write bouncing off an
/// unreachable leader parks as soon as a handoff opens the stash —
/// because each retry re-enters the stash check — and is then delivered
/// by the drain to the recovered target. The client sees one slow
/// success; the pod failure and the handoff are both invisible.
#[tokio::test]
async fn a_bouncing_live_write_parks_once_the_stash_opens() {
    let person = create_test_person();
    // Reserve an address with nothing listening on it, so live forwards
    // fail at the transport layer until the leader starts.
    let reserved = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let leader_addr = reserved.local_addr().unwrap();
    drop(reserved);

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = RouterStashHandler::new(
        Arc::clone(&backend),
        Duration::from_secs(60),
        4,
        test_store().await,
    );

    let partition = backend.partition_for_person(person.team_id, person.id);
    let req = mk_request(person.team_id, person.id, "live-transport@example.com");
    let backend_for_call = Arc::clone(&backend);
    let pending = tokio::spawn(async move { forward(&backend_for_call, req).await });

    // A handoff opens the stash while the write is bouncing; its next
    // re-entry parks it.
    tokio::time::sleep(Duration::from_millis(50)).await;
    handler.begin_stash(partition, "leader-new").await.unwrap();
    tokio::time::sleep(Duration::from_millis(200)).await;

    // The replacement leader comes up and the handoff completes; the
    // drain delivers the parked write.
    start_test_leader_at(
        leader_addr,
        TestLeaderService::new().with_person(person.clone()),
    )
    .await;
    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();

    let response = pending.await.unwrap();
    decode_response::<UpdatePersonPropertiesResponse>(response)
        .await
        .expect("the drain must deliver the write that parked mid-retry");
}

/// The reason strong reads stash at all: a write parked in the stash is
/// invisible everywhere until drain, so a strong read that raced ahead to
/// the (frozen) old owner would violate read-your-write for the whole
/// handoff window. Stashed behind the write in the same per-key FIFO, the
/// read drains after it and observes it.
#[tokio::test]
async fn stashed_strong_read_observes_stashed_write() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = new_test_handler(Arc::clone(&backend)).await;

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Write first, then a strong read for the same person — both park.
    let backend_w = Arc::clone(&backend);
    let req = mk_request(person.team_id, person.id, "stashed-write@example.com");
    let write = tokio::spawn(async move { forward(&backend_w, req).await });
    tokio::time::sleep(Duration::from_millis(50)).await;
    let backend_r = Arc::clone(&backend);
    let (team_id, person_id) = (person.team_id, person.id);
    let read = tokio::spawn(async move { forward_read(&backend_r, team_id, person_id).await });
    tokio::time::sleep(Duration::from_millis(50)).await;
    assert!(
        !write.is_finished() && !read.is_finished(),
        "both must park"
    );

    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();

    let write_resp = decode_response::<UpdatePersonPropertiesResponse>(write.await.unwrap())
        .await
        .expect("stashed write must succeed on drain");
    assert!(write_resp.updated);

    let read_resp = decode_response::<GetPersonResponse>(read.await.unwrap())
        .await
        .expect("stashed read must succeed on drain");
    let props: serde_json::Value =
        serde_json::from_slice(&read_resp.person.expect("person").properties).unwrap();
    assert_eq!(
        props["email"], "stashed-write@example.com",
        "the drained read must observe the write stashed before it"
    );
}

/// A stashed strong read is bounded by the same per-request deadline as a
/// write: past `max_stash_wait` it fails fast with retryable UNAVAILABLE
/// instead of parking until the client's gRPC deadline.
#[tokio::test]
async fn stashed_read_past_deadline_returns_unavailable() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = RouterStashHandler::new(
        Arc::clone(&backend),
        Duration::from_millis(50),
        4,
        test_store().await,
    );

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    let backend_r = Arc::clone(&backend);
    let (team_id, person_id) = (person.team_id, person.id);
    let read = tokio::spawn(async move { forward_read(&backend_r, team_id, person_id).await });
    tokio::time::sleep(Duration::from_millis(100)).await;

    handler
        .drain_stash(partition, "leader-new", CancellationToken::new())
        .await
        .unwrap();

    let code = decode_response::<GetPersonResponse>(read.await.unwrap())
        .await
        .expect_err("past-deadline read must fail fast");
    assert_eq!(
        code,
        Code::Unavailable,
        "past-deadline stashed reads must surface as retryable UNAVAILABLE"
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

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash.clone()).await;
    let handler = Arc::new(new_test_handler(Arc::clone(&backend)).await);

    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-new").await.unwrap();

    // Pre-stash a few requests so drain has something to chew on.
    let mut pending: Vec<_> = Vec::new();
    for _ in 0..5 {
        let backend = Arc::clone(&backend);
        let req = mk_request(person.team_id, person.id, "x@example.com");
        pending.push(tokio::spawn(async move { forward(&backend, req).await }));
    }
    tokio::time::sleep(Duration::from_millis(20)).await;

    // Spawn a drain task and a concurrent arrival task that keeps
    // pushing requests for ~200ms.
    let drain_handler = Arc::clone(&handler);
    let drain_task = tokio::spawn(async move {
        drain_handler
            .drain_stash(partition, "leader-new", CancellationToken::new())
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
                .push(tokio::spawn(async move { forward(&backend, req).await }));
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    });

    // Drain must terminate even with the arrival pressure. If the
    // loop fails to converge, this `await` will hang and the test
    // harness will time out.
    drain_task.await.unwrap();
    arrival_task.await.unwrap();

    // Every spawned request — pre-stashed and during-drain — must
    // produce a definitive result. We don't care which; the point is
    // that drain converged and every parked future was released.
    for h in pending {
        drop(h.await.unwrap());
    }
    let arrivals = std::mem::take(&mut *arrival_pending.lock().unwrap());
    for h in arrivals {
        drop(h.await.unwrap());
    }
}

/// Cancelling a drain mid-forward must return promptly and put the entry
/// back — not ride out the backend timeout. At router shutdown the
/// drain-lane join sits between cancellation and the lease revoke, so a
/// forward that keeps a lane busy delays deregistration, and every
/// freeze quorum still counting this router stalls with it.
#[tokio::test]
async fn drain_cancellation_returns_promptly_and_puts_the_entry_back() {
    // A leader that accepts TCP connections but never speaks: the
    // forward hangs in the HTTP/2 handshake until the backend timeout.
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind hanging leader");
    let leader_addr = listener.local_addr().expect("addr");
    tokio::spawn(async move {
        let mut held = Vec::new();
        while let Ok((sock, _)) = listener.accept().await {
            held.push(sock);
        }
    });

    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog());
    let backend = make_backend(leader_addr, stash).await;
    let handler = new_test_handler(Arc::clone(&backend)).await;

    let (team_id, person_id) = (1, 42);
    let partition = backend.partition_for_person(team_id, person_id);
    handler
        .begin_stash(partition, "leader-new")
        .await
        .expect("begin_stash should succeed");

    let req = mk_request(team_id, person_id, "parked@example.com");
    let backend_for_call = Arc::clone(&backend);
    let _in_flight = tokio::spawn(async move { forward(&backend_for_call, req).await });
    tokio::time::sleep(Duration::from_millis(50)).await;

    let cancel = CancellationToken::new();
    let drain_cancel = cancel.clone();
    let drain = tokio::spawn(async move {
        handler
            .drain_stash(partition, "leader-new", drain_cancel)
            .await
    });
    // Let the drain reach the hanging forward before cancelling.
    tokio::time::sleep(Duration::from_millis(300)).await;
    cancel.cancel();

    tokio::time::timeout(Duration::from_secs(1), drain)
        .await
        .expect("cancelled drain must return well before the backend timeout")
        .expect("drain task must not panic")
        .expect("a cancelled drain is a pause, not an error");

    let handler = new_test_handler(Arc::clone(&backend)).await;
    assert!(
        handler.stash_pending(partition),
        "the abandoned entry must be put back for the next drain"
    );
}

/// A drain toward nobody (a partition no handoff or assignment names) still
/// answers what outlived the stash wait and closes the freeze.
#[tokio::test]
async fn a_drain_toward_nobody_answers_expired_requests_and_ends_the_freeze() {
    let changelog = changelog();
    let backend = Arc::new(LeaderBackend::new(
        Arc::new(RwLock::new(HashMap::new())),
        Arc::new(|_: &str| None),
        LeaderBackendConfig {
            changelog: changelog.clone(),
            timeout: Duration::from_secs(5),
            num_channels: 1,
            http2_windows: Http2Windows::default(),
        },
        StashTable::with_bounds(usize::MAX, usize::MAX, changelog),
    ));
    let handler = RouterStashHandler::new(
        Arc::clone(&backend),
        Duration::from_millis(50),
        4,
        test_store().await,
    );
    let partition = backend.partition_for_person(1, 1);
    handler.begin_stash(partition, "leader-gone").await.unwrap();
    let backend_for_call = Arc::clone(&backend);
    let in_flight =
        tokio::spawn(
            async move { forward(&backend_for_call, mk_request(1, 1, "x@example.com")).await },
        );
    tokio::time::sleep(Duration::from_millis(100)).await;

    handler
        .drain_stash(partition, "", CancellationToken::new())
        .await
        .unwrap();

    let raw = tokio::time::timeout(Duration::from_secs(2), in_flight)
        .await
        .expect("the drain answers the expired request")
        .unwrap();
    assert_eq!(
        decode_response::<UpdatePersonPropertiesResponse>(raw)
            .await
            .err(),
        Some(Code::Unavailable)
    );
    assert!(!handler.stash_pending(partition));
}

/// A backend whose table sends every partition below `partitions` to
/// `leader-0` at `leader_addr`.
fn backend_routing_all(
    leader_addr: std::net::SocketAddr,
    partitions: u32,
    changelog: LiveChangelog,
) -> Arc<LeaderBackend> {
    let leader_url = format!("http://{leader_addr}");
    Arc::new(LeaderBackend::new(
        Arc::new(RwLock::new(
            (0..partitions)
                .map(|partition| (partition, "leader-0".to_string()))
                .collect::<HashMap<_, _>>(),
        )),
        Arc::new(move |_: &str| Some(leader_url.clone())),
        LeaderBackendConfig {
            changelog: changelog.clone(),
            timeout: Duration::from_secs(5),
            num_channels: 1,
            http2_windows: Http2Windows::default(),
        },
        StashTable::with_bounds(usize::MAX, usize::MAX, changelog),
    ))
}

/// A drain that beats the config watch reads the config first and takes the right keys.
#[tokio::test]
async fn a_drain_adopts_the_config_from_etcd_first() {
    let person_id = moving_person();
    let person = Person {
        id: person_id,
        team_id: 1,
        ..create_test_person()
    };
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person)).await;
    let backend = backend_routing_all(leader_addr, NUM_PARTITIONS * 2, changelog());
    let store = test_store().await;
    store.put_changelog_config(&grown_config()).await.unwrap();
    let handler = RouterStashHandler::new(Arc::clone(&backend), TEST_MAX_STASH_WAIT, 1, store);
    handler
        .begin_stash(
            partition_for_person(1, person_id, NUM_PARTITIONS),
            "leader-0",
        )
        .await
        .unwrap();
    let backend_for_call = Arc::clone(&backend);
    let in_flight = tokio::spawn(async move {
        forward(&backend_for_call, mk_request(1, person_id, "x@example.com")).await
    });
    tokio::time::sleep(Duration::from_millis(50)).await;
    assert!(!in_flight.is_finished(), "the write parks");

    let new_partition = partition_for_person(1, person_id, NUM_PARTITIONS * 2);
    handler
        .drain_stash(new_partition, "leader-0", CancellationToken::new())
        .await
        .unwrap();

    let raw = tokio::time::timeout(Duration::from_secs(2), in_flight)
        .await
        .expect("the drain delivers the parked write")
        .unwrap();
    assert!(decode_response::<UpdatePersonPropertiesResponse>(raw)
        .await
        .is_ok());
}

/// The config read is best effort: when it fails, the drain still runs under
/// the count the router holds.
#[tokio::test]
async fn a_drain_runs_when_its_config_read_fails() {
    let person = create_test_person();
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;
    let backend = backend_routing_all(leader_addr, NUM_PARTITIONS, changelog());
    // Nothing listens on port 1, so the read fails.
    let unreachable = EtcdStore::connect(StoreConfig {
        endpoints: vec!["http://127.0.0.1:1".to_string()],
        prefix: "/stash-test-unreachable/".to_string(),
    })
    .await
    .expect("the etcd client connects lazily");
    let handler = RouterStashHandler::new(
        Arc::clone(&backend),
        TEST_MAX_STASH_WAIT,
        1,
        Arc::new(PersonhogStore::new(unreachable)),
    );
    let partition = backend.partition_for_person(person.team_id, person.id);
    handler.begin_stash(partition, "leader-0").await.unwrap();
    let backend_for_call = Arc::clone(&backend);
    let in_flight = tokio::spawn(async move {
        forward(
            &backend_for_call,
            mk_request(person.team_id, person.id, "x@example.com"),
        )
        .await
    });
    tokio::time::sleep(Duration::from_millis(50)).await;

    handler
        .drain_stash(partition, "leader-0", CancellationToken::new())
        .await
        .unwrap();

    let raw = tokio::time::timeout(Duration::from_secs(2), in_flight)
        .await
        .expect("the drain delivers the parked write")
        .unwrap();
    assert!(decode_response::<UpdatePersonPropertiesResponse>(raw)
        .await
        .is_ok());
}

/// A person whose partition differs between the current and the grown count.
fn moving_person() -> i64 {
    (1..)
        .find(|id| {
            partition_for_person(1, *id, NUM_PARTITIONS)
                != partition_for_person(1, *id, NUM_PARTITIONS * 2)
        })
        .unwrap()
}

fn grown_config() -> ChangelogConfig {
    ChangelogConfig {
        epoch: 2,
        ..ChangelogConfig::new("personhog_updates_v2", NUM_PARTITIONS * 2)
    }
}

/// The config watch adopts a flip from etcd, and the new partition's drain
/// delivers a parked key once the old partition's drain gives it back.
#[tokio::test]
async fn a_flip_in_etcd_moves_a_parked_key_to_its_new_partition() {
    let store = test_store().await;
    assert!(store
        .seed_changelog_config("personhog_updates", NUM_PARTITIONS, "personhog-writer")
        .await
        .unwrap());
    let person = Person {
        id: moving_person(),
        ..create_test_person()
    };
    let leader_addr = start_test_leader(TestLeaderService::new().with_person(person.clone())).await;
    let changelog = changelog();
    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog.clone());
    let backend = backend_with(
        leader_addr,
        changelog.clone(),
        stash.clone(),
        NUM_PARTITIONS * 2,
    )
    .await;
    let handler = RouterStashHandler::new(
        Arc::clone(&backend),
        Duration::from_secs(60),
        4,
        Arc::clone(&store),
    );
    let old_partition = partition_for_person(1, person.id, NUM_PARTITIONS);
    let new_partition = partition_for_person(1, person.id, NUM_PARTITIONS * 2);

    stash.begin_stash(old_partition);
    let backend_for_call = Arc::clone(&backend);
    let req = mk_request(1, person.id, "moved@example.com");
    let pending = tokio::spawn(async move { forward(&backend_for_call, req).await });
    let holder = stash.drain_session(old_partition).unwrap();
    let mut held = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let taken = holder.take_for_attempt(usize::MAX);
            if !taken.is_empty() {
                return taken;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("the old partition's drain takes the parked request");

    store.put_changelog_config(&grown_config()).await.unwrap();
    let cancel = CancellationToken::new();
    tokio::spawn(personhog_coordination::changelog::keep_changelog_live(
        Arc::clone(&store),
        changelog.clone(),
        cancel.clone(),
    ));
    tokio::time::timeout(Duration::from_secs(5), async {
        while !stash.is_pending(new_partition) {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("the parked key belongs to its partition under the adopted count");

    let mut drain = tokio::spawn(async move {
        handler
            .drain_stash(new_partition, "leader-0", CancellationToken::new())
            .await
    });
    assert!(
        tokio::time::timeout(Duration::from_millis(200), &mut drain)
            .await
            .is_err(),
        "the new drain waits while the old one holds the key"
    );
    let run = held.remove(0);
    holder.put_back(run.key, run.entries);

    tokio::time::timeout(Duration::from_secs(5), drain)
        .await
        .expect("the drain settles once it delivers the key")
        .expect("drain task must not panic")
        .expect("drain succeeds");
    decode_response::<UpdatePersonPropertiesResponse>(pending.await.unwrap())
        .await
        .expect("the parked write is delivered through the new partition");
    cancel.cancel();
}

/// A retry after a bounce recomputes the partition, so it sees the freeze
/// on the key's new partition instead of forwarding under the old count.
#[tokio::test]
async fn a_retry_after_a_bounce_routes_by_the_adopted_count() {
    let person_id = moving_person();
    let new_partition = partition_for_person(1, person_id, NUM_PARTITIONS * 2);
    let changelog = changelog();
    let stash = StashTable::with_bounds(usize::MAX, usize::MAX, changelog.clone());
    let flipped = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let service = TestLeaderService::new().fenced().on_write({
        let (changelog, stash) = (changelog.clone(), stash.clone());
        move || {
            if !flipped.swap(true, Ordering::SeqCst) {
                changelog.adopt(&grown_config());
                stash.begin_stash(new_partition);
            }
        }
    });
    let leader_addr = start_test_leader(service).await;
    let backend = backend_with(leader_addr, changelog, stash.clone(), NUM_PARTITIONS * 2).await;

    let req = mk_request(1, person_id, "retried@example.com");
    let pending = tokio::spawn(async move { forward(&backend, req).await });
    let session = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if let Some(session) = stash.drain_session(new_partition) {
                return session;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("the first attempt freezes the new partition");
    let taken = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let taken = session.take_for_attempt(usize::MAX);
            if !taken.is_empty() {
                return taken;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("the retry parks behind the new partition's freeze");
    assert_eq!(taken[0].key, (1, person_id));
    assert!(!pending.is_finished());
}
