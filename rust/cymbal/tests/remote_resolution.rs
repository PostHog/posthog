//! Integration tests for the Batch 3 remote-resolution client path.
//!
//! Shared fixtures live in `tests/common/mod.rs`; this file owns the original
//! Batch 3 acceptance tests covering the happy path, transport retries, and
//! the contract that there is no silent local fallback when remote mode is
//! enabled. Failure-mode hardening tests added in Batch 4 live in
//! `tests/remote_resolution_hardening.rs`.

mod common;

use std::collections::HashSet;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common::{
    build_event, local_stage, make_ctx, make_ctx_with_sample_rate,
    make_ctx_with_sample_rate_and_limits, process_one, remote_stage, spawn_recording_stub_server,
    spawn_stub_server, ServerBehavior,
};

use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::apple::AppleDebugImage;
use cymbal::stages::resolution::symbol::SymbolResolver;
use cymbal::stages::resolution::ResolutionStage;
use cymbal::symbol_store::chunk_id::OrChunkId;
use cymbal::symbol_store::proguard::ProguardRef;
use cymbal::types::batch::Batch;
use cymbal::types::exception_properties::ExceptionProperties;
use cymbal::types::operator::TeamId;
use cymbal::types::stage::Stage;
use cymbal::types::Stacktrace;
use serde_json::json;
use sha2::{Digest, Sha256};
use tokio::sync::Semaphore;
use uuid::Uuid;

#[derive(Default)]
struct CountingResolver {
    raw_frame_calls: AtomicUsize,
    dart_name_calls: AtomicUsize,
}

#[async_trait]
impl SymbolResolver for CountingResolver {
    async fn resolve_raw_frame(
        &self,
        _team_id: TeamId,
        _frame: &RawFrame,
        _debug_images: &[AppleDebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.raw_frame_calls.fetch_add(1, Ordering::SeqCst);
        Ok(Vec::new())
    }

    async fn resolve_java_class(
        &self,
        _team_id: TeamId,
        _symbolset_ref: OrChunkId<ProguardRef>,
        _class: String,
    ) -> Result<String, ResolveError> {
        unreachable!("sampling integration fixtures do not exercise Java resolution")
    }

    async fn resolve_dart_minified_name(
        &self,
        _team_id: TeamId,
        _symbolset_ref: String,
        _minified_name: &str,
    ) -> Result<String, ResolveError> {
        self.dart_name_calls.fetch_add(1, Ordering::SeqCst);
        Ok("ResolvedDart".to_string())
    }
}

fn remote_stage_with_resolver(
    ctx: cymbal::stages::resolution::remote::resolver::RemoteResolutionContext,
    resolver: Arc<CountingResolver>,
) -> ResolutionStage {
    ResolutionStage {
        symbol_resolver: resolver,
        symbol_resolution_limiter: Arc::new(Semaphore::new(4)),
        remote: Some(ctx),
    }
}

fn build_dart_event() -> ExceptionProperties {
    let mut evt: ExceptionProperties = serde_json::from_value(json!({
        "$exception_list": [{
            "type": "minified:Foo",
            "value": "boom",
            "stacktrace": {
                "type": "raw",
                "frames": [{
                    "platform": "web:javascript",
                    "filename": "https://example.com/app.js",
                    "function": "a",
                    "lineno": 1,
                    "colno": 2,
                    "chunk_id": "chunk-a"
                }]
            }
        }]
    }))
    .expect("valid exception properties");
    evt.team_id = 7;
    evt.uuid = Uuid::from_u128(42);
    evt
}

fn build_event_with_symbol_refs(uuid: Uuid, symbol_refs: &[&str]) -> ExceptionProperties {
    let exceptions: Vec<serde_json::Value> = symbol_refs
        .iter()
        .enumerate()
        .map(|(idx, symbol_ref)| {
            json!({
                "type": format!("Boom{idx}"),
                "value": format!("message {idx}"),
                "stacktrace": {
                    "type": "raw",
                    "frames": [{
                        "platform": "web:javascript",
                        "filename": "https://example.com/app.js",
                        "function": "minified",
                        "lineno": 1,
                        "colno": 2,
                        "chunk_id": symbol_ref
                    }]
                }
            })
        })
        .collect();
    let mut evt: ExceptionProperties = serde_json::from_value(json!({
        "$exception_list": exceptions
    }))
    .expect("valid exception properties");
    evt.team_id = 7;
    evt.uuid = uuid;
    evt
}

fn sampling_bucket(team_id: i32, uuid: Uuid) -> f64 {
    let mut hasher = Sha256::new();
    hasher.update(team_id.to_be_bytes());
    hasher.update(uuid.as_bytes());
    let digest = hasher.finalize();
    let bucket_bytes: [u8; 8] = digest[..8]
        .try_into()
        .expect("sha256 digest always contains at least 8 bytes");
    u64::from_be_bytes(bucket_bytes) as f64 / ((u64::MAX as f64) + 1.0)
}

fn uuid_for_sampling_decision(team_id: i32, sample_rate: f64, want_remote: bool) -> Uuid {
    for candidate in 1..10_000u128 {
        let uuid = Uuid::from_u128(candidate);
        if (sampling_bucket(team_id, uuid) < sample_rate) == want_remote {
            return uuid;
        }
    }
    panic!("failed to find deterministic sampling fixture");
}

#[tokio::test]
async fn happy_path_preserves_batch_event_and_exception_order() {
    let (addr, _) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;
    let evt_a = build_event(3);
    let evt_b = build_event(2);
    let expected_uuids = [evt_a.uuid, evt_b.uuid];
    let expected_types: Vec<Vec<_>> = [&evt_a, &evt_b]
        .into_iter()
        .map(|evt| {
            evt.exception_list
                .iter()
                .map(|e| e.exception_type.clone())
                .collect()
        })
        .collect();

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt_a), Ok(evt_b)]))
        .await
        .expect("stage processed");
    let resolved: Vec<_> = result
        .into_iter()
        .map(|item| item.expect("event must not be EventError"))
        .collect();

    assert_eq!(resolved.len(), 2);
    assert_eq!(resolved[0].uuid, expected_uuids[0]);
    assert_eq!(resolved[1].uuid, expected_uuids[1]);
    let resolved_types: Vec<Vec<_>> = resolved
        .iter()
        .map(|evt| {
            evt.exception_list
                .iter()
                .map(|e| e.exception_type.clone())
                .collect()
        })
        .collect();
    assert_eq!(resolved_types, expected_types);
    for (resolved_evt, expected_evt_types) in resolved.iter().zip(expected_types.iter()) {
        let mut expected_properties = expected_evt_types.clone();
        expected_properties.sort();
        let mut resolved_properties = resolved_evt.exception_types.clone().unwrap_or_default();
        resolved_properties.sort();
        assert_eq!(resolved_properties, expected_properties);
    }
}

#[tokio::test]
async fn local_mode_ignores_remote_pool_when_remote_is_disabled() {
    let (_addr, hits) = spawn_stub_server(ServerBehavior::AlwaysInvalidArgument).await;
    let evt = build_event(3);
    let original_types: Vec<_> = evt
        .exception_list
        .iter()
        .map(|e| e.exception_type.clone())
        .collect();

    let resolved = process_one(local_stage(), evt)
        .await
        .expect("no unhandled error");

    assert_eq!(resolved.exception_list.len(), 3);
    let resolved_types: Vec<_> = resolved
        .exception_list
        .iter()
        .map(|e| e.exception_type.clone())
        .collect();
    assert_eq!(resolved_types, original_types);
    let mut expected_properties = original_types.clone();
    expected_properties.sort();
    let mut resolved_properties = resolved.exception_types.unwrap_or_default();
    resolved_properties.sort();
    assert_eq!(resolved_properties, expected_properties);
    assert!(
        hits.lock().unwrap().is_empty(),
        "disabled remote mode must not call the remote pool"
    );
}

#[tokio::test]
async fn sample_rate_zero_routes_eligible_events_locally_without_remote_calls() {
    let (addr, hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx_with_sample_rate(&[addr], 0, Duration::from_secs(5), 0.0).await;
    let evt = build_event(1);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("sampled-local event should resolve locally");

    assert!(
        hits.lock().unwrap().is_empty(),
        "sample_rate=0.0 must not call cymbal-resolution"
    );
    assert!(matches!(
        resolved
            .exception_list
            .first()
            .and_then(|e| e.stack.as_ref()),
        Some(Stacktrace::Resolved { .. })
    ));
    assert_eq!(resolved.exception_types, Some(vec!["Boom0".to_string()]));
}

#[tokio::test]
async fn sample_rate_one_routes_all_eligible_events_remotely() {
    let (addr, hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx_with_sample_rate(&[addr], 0, Duration::from_secs(5), 1.0).await;
    let evt_a = build_event(1);
    let evt_b = build_event(2);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt_a), Ok(evt_b)]))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 2);

    assert_eq!(
        hits.lock().unwrap().len(),
        1,
        "sample_rate=1.0 should group eligible events that share a routing key"
    );
}

#[tokio::test]
async fn exceptions_with_same_routing_key_share_one_resolve_request() {
    let (addr, _hits, requests) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;
    let evt_a = build_event_with_symbol_refs(Uuid::from_u128(101), &["shared-bundle"]);
    let evt_b = build_event_with_symbol_refs(Uuid::from_u128(102), &["shared-bundle"]);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt_a), Ok(evt_b)]))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 2);

    let requests = requests.lock().unwrap();
    assert_eq!(requests.len(), 1, "same routing key should batch together");
    assert_eq!(requests[0].items.len(), 2);
    assert_eq!(requests[0].items[0].item_index, 0);
    assert_eq!(requests[0].items[1].item_index, 1);
}

#[tokio::test]
async fn exceptions_with_distinct_symbol_sets_share_one_request_under_per_team_routing() {
    // Per-team routing means an event's exceptions all go to one pod even
    // when they reference distinct symbol sets — they share `team:{team_id}`
    // as the routing key. Previously this used to fan out per-symbol-set.
    let (addr, _hits, requests) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;
    let evt = build_event_with_symbol_refs(Uuid::from_u128(201), &["bundle-a", "bundle-b"]);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt)]))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 1);

    let requests = requests.lock().unwrap();
    assert_eq!(
        requests.len(),
        1,
        "per-team routing collapses distinct symbol sets into one RPC",
    );
    assert_eq!(requests[0].items.len(), 2);
    let mut item_indices: Vec<u32> = requests[0]
        .items
        .iter()
        .map(|item| item.item_index)
        .collect();
    item_indices.sort();
    assert_eq!(item_indices, vec![0, 1]);
}

#[tokio::test]
async fn chunks_split_at_event_boundaries_up_to_max_items() {
    // Event-atomic chunking: three events of sizes (2, 2, 1) with max_items=2
    // produce three chunks that match the event sizes exactly. We never split
    // an event's exceptions across chunks.
    let (addr, _hits, requests) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx =
        make_ctx_with_sample_rate_and_limits(&[addr], 0, Duration::from_secs(5), 1.0, 2).await;
    let evt_a = build_event_with_symbol_refs(Uuid::from_u128(301), &["a", "a"]);
    let evt_b = build_event_with_symbol_refs(Uuid::from_u128(302), &["b", "b"]);
    let evt_c = build_event_with_symbol_refs(Uuid::from_u128(303), &["c"]);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt_a), Ok(evt_b), Ok(evt_c)]))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 3);

    let item_counts: Vec<usize> = requests
        .lock()
        .unwrap()
        .iter()
        .map(|request| request.items.len())
        .collect();
    assert_eq!(item_counts, vec![2, 2, 1]);
}

#[tokio::test]
async fn server_suggested_batch_size_shrinks_chunks_below_client_config() {
    // The stub server advertises `suggested_batch_size = 8` on every
    // LoadEvent (see tests/common/mod.rs). With a client config of 64,
    // chunks must honor the smaller server-driven cap. Build 10 single-
    // exception events; expect chunks of size 8 + 2.
    let (addr, _hits, requests) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx =
        make_ctx_with_sample_rate_and_limits(&[addr], 0, Duration::from_secs(5), 1.0, 64).await;
    let events: Vec<_> = (0..10)
        .map(|i| {
            Ok(build_event_with_symbol_refs(
                Uuid::from_u128(500 + i),
                &["x"],
            ))
        })
        .collect();

    let result = remote_stage(ctx)
        .process(Batch::from(events))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 10);

    let item_counts: Vec<usize> = requests
        .lock()
        .unwrap()
        .iter()
        .map(|request| request.items.len())
        .collect();
    assert_eq!(
        item_counts,
        vec![8, 2],
        "server suggestion (8) must beat client config (64)"
    );
}

#[tokio::test]
async fn single_oversized_event_ships_as_one_chunk() {
    // A single event whose exception count exceeds max_items can't be split
    // (event-atomic chunking); it goes out as one oversized chunk. The byte
    // cap that used to enforce a hard 1 MiB wire limit is gone — the server
    // is responsible for signalling back (future LoadEvent extension) when
    // it wants smaller batches.
    let (addr, _hits, requests) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx =
        make_ctx_with_sample_rate_and_limits(&[addr], 0, Duration::from_secs(5), 1.0, 2).await;
    let evt = build_event_with_symbol_refs(Uuid::from_u128(304), &["x", "x", "x", "x", "x"]);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt)]))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 1);

    let item_counts: Vec<usize> = requests
        .lock()
        .unwrap()
        .iter()
        .map(|request| request.items.len())
        .collect();
    assert_eq!(item_counts, vec![5]);
}

#[tokio::test]
async fn retrying_a_per_team_group_replays_the_full_request() {
    // Under per-team routing all of an event's exceptions land in one
    // RPC. When the server signals a retry, the entire request is replayed
    // against (potentially) another endpoint; the test asserts we don't
    // duplicate items mid-replay.
    let (addr, _hits, requests) = spawn_recording_stub_server(ServerBehavior::RetryUntil {
        retry_until_attempt: 1,
    })
    .await;
    let ctx = make_ctx(&[addr], 2, Duration::from_secs(5)).await;
    let evt = build_event_with_symbol_refs(Uuid::from_u128(401), &["bundle-a", "bundle-b"]);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt)]))
        .await
        .expect("stage processed after retry");
    let resolved: Vec<_> = result
        .into_iter()
        .map(|item| item.expect("event must not be EventError"))
        .collect();
    assert_eq!(resolved[0].exception_list.len(), 2);

    let requests = requests.lock().unwrap();
    assert_eq!(
        requests.len(),
        2,
        "one retry of the per-team group means exactly two recorded RPCs",
    );
    assert!(
        requests.iter().all(|request| request.items.len() == 2),
        "each RPC must carry both exceptions of the per-team group",
    );
}

#[tokio::test]
async fn mixed_sampled_remote_and_unsampled_local_events_preserve_output_ordering() {
    let (addr, hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let sample_rate = 0.5;
    let remote_uuid = uuid_for_sampling_decision(7, sample_rate, true);
    let local_uuid = uuid_for_sampling_decision(7, sample_rate, false);
    let ctx = make_ctx_with_sample_rate(&[addr], 0, Duration::from_secs(5), sample_rate).await;
    let resolver = Arc::new(CountingResolver::default());
    let mut local_evt = build_dart_event();
    local_evt.uuid = local_uuid;
    let remote_evt = build_event_with_symbol_refs(remote_uuid, &["remote-bundle"]);

    let result = remote_stage_with_resolver(ctx, resolver.clone())
        .process(Batch::from(vec![
            Ok(local_evt.clone()),
            Ok(remote_evt.clone()),
        ]))
        .await
        .expect("stage processed");
    let resolved: Vec<_> = result
        .into_iter()
        .map(|item| item.expect("event must not be EventError"))
        .collect();

    assert_eq!(resolved.len(), 2);
    assert_eq!(resolved[0].uuid, local_uuid);
    assert_eq!(resolved[1].uuid, remote_uuid);
    assert_eq!(hits.lock().unwrap().len(), 1);
    assert_eq!(resolver.dart_name_calls.load(Ordering::SeqCst), 1);
    assert_eq!(resolved[0].exception_list[0].exception_type, "ResolvedDart");
    assert_eq!(resolved[1].exception_list[0].exception_type, "Boom0");
}

#[tokio::test]
async fn partial_sample_rate_is_deterministic_for_same_event() {
    let (addr, hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx_with_sample_rate(&[addr], 0, Duration::from_secs(5), 0.5).await;
    let mut evt = build_event(1);
    evt.team_id = 77;
    evt.uuid = Uuid::from_u128(0x1234);

    for _ in 0..8 {
        let _resolved = process_one(remote_stage(ctx.clone()), evt.clone())
            .await
            .expect("stage processed");
    }

    let remote_calls = hits.lock().unwrap().len();
    assert!(
        remote_calls == 0 || remote_calls == 8,
        "same team_id + event UUID must make the same sampling decision across retries; got {remote_calls} remote calls"
    );
}

#[tokio::test]
async fn sampled_remote_failure_does_not_fall_back_to_local_resolution() {
    let (addr, hits) = spawn_stub_server(ServerBehavior::AlwaysUnavailable).await;
    let ctx = make_ctx_with_sample_rate(&[addr], 0, Duration::from_secs(5), 1.0).await;
    let resolver = Arc::new(CountingResolver::default());

    let err = process_one(
        remote_stage_with_resolver(ctx, resolver.clone()),
        build_dart_event(),
    )
    .await
    .expect_err("sampled remote failure must surface");

    assert!(format!("{err}").contains("exhausted"));
    assert_eq!(hits.lock().unwrap().len(), 1);
    assert_eq!(resolver.dart_name_calls.load(Ordering::SeqCst), 0);
    assert_eq!(resolver.raw_frame_calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn unsampled_events_run_local_exception_frame_and_properties_resolvers() {
    let (addr, hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx_with_sample_rate(&[addr], 0, Duration::from_secs(5), 0.0).await;
    let resolver = Arc::new(CountingResolver::default());

    let resolved = process_one(
        remote_stage_with_resolver(ctx, resolver.clone()),
        build_dart_event(),
    )
    .await
    .expect("unsampled event should resolve locally");

    assert!(hits.lock().unwrap().is_empty());
    assert_eq!(resolver.dart_name_calls.load(Ordering::SeqCst), 1);
    assert_eq!(resolver.raw_frame_calls.load(Ordering::SeqCst), 1);
    assert_eq!(resolved.exception_list[0].exception_type, "ResolvedDart");
    assert!(matches!(
        resolved.exception_list[0].stack.as_ref(),
        Some(Stacktrace::Resolved { .. })
    ));
    assert_eq!(
        resolved.exception_types,
        Some(vec!["ResolvedDart".to_string()])
    );
}

#[tokio::test]
async fn transport_unavailable_retries_against_another_endpoint() {
    // Use a single Unavailable endpoint so the very first attempt fails; the
    // pool then has to rotate to the Happy endpoint on retry. This sidesteps
    // round-robin selection order, which otherwise leaves the test dependent
    // on the OS-assigned port ordering.
    let (bad_addr, bad_hits) = spawn_stub_server(ServerBehavior::AlwaysUnavailable).await;
    let (good_addr, good_hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[bad_addr, good_addr], 4, Duration::from_secs(5)).await;
    let evt = build_event(1);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("stage succeeded");
    assert_eq!(resolved.exception_list.len(), 1);

    // With max_retries=4 against a 2-endpoint pool, the caller is allowed up
    // to 5 attempts; the bad endpoint can be hit zero or more times depending
    // on round-robin order, but the good endpoint MUST end up serving the
    // successful attempt at least once.
    let touched: HashSet<SocketAddr> = bad_hits
        .lock()
        .unwrap()
        .iter()
        .chain(good_hits.lock().unwrap().iter())
        .copied()
        .collect();
    assert!(
        touched.contains(&good_addr),
        "good endpoint must have served the successful retry, touched={touched:?}"
    );
}

#[tokio::test]
async fn per_item_retry_outcome_triggers_caller_side_retry() {
    let (addr, _) = spawn_stub_server(ServerBehavior::RetryUntil {
        retry_until_attempt: 1,
    })
    .await;
    let ctx = make_ctx(&[addr], 3, Duration::from_secs(5)).await;
    let evt = build_event(1);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("stage succeeded");
    assert_eq!(resolved.exception_list.len(), 1);
}

#[tokio::test]
async fn terminal_status_surfaces_as_unhandled_error_without_retry() {
    let (addr, hits) = spawn_stub_server(ServerBehavior::AlwaysInvalidArgument).await;
    let ctx = make_ctx(&[addr], 5, Duration::from_secs(5)).await;
    let evt = build_event(1);

    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("terminal status must surface as unhandled error");

    let msg = format!("{err}");
    assert!(
        msg.contains("terminal"),
        "expected terminal failure, got: {msg}"
    );
    // Only one attempt — terminal statuses should not be retried.
    assert_eq!(hits.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn caller_deadline_cancels_slow_request_and_retries() {
    let (slow_addr, _) = spawn_stub_server(ServerBehavior::SlowerThanDeadline {
        sleep: Duration::from_millis(400),
    })
    .await;
    let (fast_addr, _) = spawn_stub_server(ServerBehavior::Happy).await;

    let ctx = make_ctx(&[slow_addr, fast_addr], 2, Duration::from_millis(150)).await;
    let evt = build_event(1);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("stage succeeded after retry");
    assert_eq!(resolved.exception_list.len(), 1);
}

#[tokio::test]
async fn empty_pool_fails_clearly_without_local_fallback() {
    let ctx = make_ctx(&[], 0, Duration::from_secs(1)).await;
    let evt = build_event(1);
    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("empty pool must surface as unhandled error");
    let msg = format!("{err}");
    assert!(
        msg.contains("pool unavailable"),
        "expected pool-empty error, got: {msg}"
    );
}

#[tokio::test]
async fn exhausting_retries_returns_unhandled_error_with_no_local_fallback() {
    let (addr, hits) = spawn_stub_server(ServerBehavior::AlwaysUnavailable).await;
    let ctx = make_ctx(&[addr], 1, Duration::from_secs(5)).await;
    let evt = build_event(1);
    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("exhausted retries must surface as unhandled error");
    let msg = format!("{err}");
    assert!(
        msg.contains("exhausted"),
        "expected exhaustion error, got: {msg}"
    );
    // max_retries=1 → 2 attempts total against the only endpoint.
    assert_eq!(hits.lock().unwrap().len(), 2);
}
