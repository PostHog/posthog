//! Integration tests for the Batch 3 remote-resolution client path.
//!
//! Shared fixtures live in `tests/common/mod.rs`; this file owns the original
//! Batch 3 acceptance tests covering the happy path, transport retries, and
//! the contract that there is no silent local fallback when remote mode is
//! enabled. Failure-mode hardening tests added in Batch 4 live in
//! `tests/remote_resolution_hardening.rs`.

mod common;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common::{
    build_event, local_stage, make_ctx, make_ctx_with_sample_rate, process_one, remote_stage,
    spawn_recording_stub_server, spawn_stub_server, ServerBehavior,
};

use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::native::DebugImage;
use cymbal::stages::resolution::ResolutionStage;
use cymbal::symbolication::symbol::SymbolResolver;
use cymbal::symbolication::symbol_store::chunk_id::OrChunkId;
use cymbal::symbolication::symbol_store::proguard::ProguardRef;
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
        _debug_images: &[DebugImage],
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
        3,
        "sample_rate=1.0 should submit one streamed item per exception"
    );
}

#[tokio::test]
async fn exceptions_with_same_routing_key_submit_independent_stream_items() {
    let (addr, _streams, items) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;
    let evt_a = build_event_with_symbol_refs(Uuid::from_u128(101), &["shared-bundle"]);
    let evt_b = build_event_with_symbol_refs(Uuid::from_u128(102), &["shared-bundle"]);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt_a), Ok(evt_b)]))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 2);

    let items = items.lock().unwrap();
    assert_eq!(items.len(), 2, "each exception should be a streamed item");
    assert!(items.iter().all(|item| item.team_id == 7));
    assert!(items.iter().all(|item| item.deadline_ms > 0));
    assert_ne!(items[0].id, items[1].id, "stream ids must be unique");
}

#[tokio::test]
async fn distinct_symbol_sets_are_streamed_as_independent_items_under_team_routing() {
    let (addr, _streams, items) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;
    let evt = build_event_with_symbol_refs(Uuid::from_u128(201), &["bundle-a", "bundle-b"]);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt)]))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 1);

    let items = items.lock().unwrap();
    assert_eq!(items.len(), 2);
    let exception_types: Vec<String> = items
        .iter()
        .map(|item| {
            let exc: cymbal::types::Exception =
                serde_json::from_slice(&item.exception_json).expect("valid exception json");
            exc.exception_type
        })
        .collect();
    assert_eq!(exception_types, vec!["Boom0", "Boom1"]);
}

#[tokio::test]
async fn load_events_do_not_shrink_streamed_item_submission() {
    let (addr, _streams, items) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx_with_sample_rate(&[addr], 0, Duration::from_secs(5), 1.0).await;
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
    assert_eq!(items.lock().unwrap().len(), 10);
}

#[tokio::test]
async fn accepted_outcomes_release_routing_slots_before_terminal_completion() {
    let (addr, _streams, items) =
        spawn_recording_stub_server(ServerBehavior::AcceptedThenDoneDelayed {
            delay: Duration::from_millis(300),
        })
        .await;
    let ctx = make_ctx_with_sample_rate(&[addr], 0, Duration::from_secs(5), 1.0).await;
    let events: Vec<_> = (0..11)
        .map(|i| {
            Ok(build_event_with_symbol_refs(
                Uuid::from_u128(600 + i),
                &["x"],
            ))
        })
        .collect();

    let task = tokio::spawn(remote_stage(ctx).process(Batch::from(events)));
    tokio::time::sleep(Duration::from_millis(100)).await;

    assert_eq!(items.lock().unwrap().len(), 11);
    task.await
        .expect("join remote resolution")
        .expect("stage processed");
}

#[tokio::test]
async fn metadata_encodes_debug_images_json() {
    let (addr, _streams, items) = spawn_recording_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;
    let mut evt = build_event(1);
    evt.debug_images = vec![DebugImage {
        debug_id: "ABCDEF".to_string(),
        image_addr: "0x100000000".to_string(),
        image_vmaddr: Some("0x100000000".to_string()),
        image_size: Some(4096),
        code_file: Some("Example.app/Example".to_string()),
        image_type: Some("macho".to_string()),
        arch: Some("arm64".to_string()),
    }];

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt)]))
        .await
        .expect("stage processed");
    assert_eq!(result.len(), 1);

    let items = items.lock().unwrap();
    assert_eq!(items.len(), 1);
    let metadata: serde_json::Value =
        serde_json::from_slice(&items[0].metadata).expect("metadata is json");
    assert_eq!(
        metadata["debug_images_json"][0]["debug_id"],
        serde_json::Value::String("ABCDEF".to_string())
    );
    // The legacy apple-specific key is no longer written.
    assert!(metadata.get("apple_debug_images_json").is_none());
}

#[tokio::test]
async fn per_item_overloaded_outcomes_reroute_independently() {
    let (overloaded_addr, overloaded_items) = spawn_stub_server(ServerBehavior::Overloaded).await;
    let (good_addr, good_items) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[overloaded_addr, good_addr], 3, Duration::from_secs(5)).await;
    let evt = build_event_with_symbol_refs(Uuid::from_u128(401), &["bundle-a", "bundle-b"]);

    let result = remote_stage(ctx)
        .process(Batch::from(vec![Ok(evt)]))
        .await
        .expect("stage processed after per-item reroute");
    let resolved: Vec<_> = result
        .into_iter()
        .map(|item| item.expect("event must not be EventError"))
        .collect();
    assert_eq!(resolved[0].exception_list.len(), 2);
    assert_eq!(good_items.lock().unwrap().len(), 2);
    assert!(
        overloaded_items.lock().unwrap().len() <= 2,
        "items may hash directly to the healthy endpoint, but overload retries must not duplicate successes"
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
    assert!(hits.lock().unwrap().is_empty());
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

    assert!(
        bad_hits.lock().unwrap().is_empty(),
        "setup-level Unavailable should fail before any items are processed"
    );
    assert_eq!(
        good_hits.lock().unwrap().len(),
        1,
        "good endpoint must serve the successful retry"
    );
}

#[tokio::test]
async fn per_item_retry_outcome_triggers_caller_side_reroute() {
    let (retry_addr, retry_items) = spawn_stub_server(ServerBehavior::Retry).await;
    let (good_addr, good_items) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[retry_addr, good_addr], 3, Duration::from_secs(5)).await;
    let evt = build_event(1);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("stage succeeded");
    assert_eq!(resolved.exception_list.len(), 1);
    assert_eq!(good_items.lock().unwrap().len(), 1);
    assert!(retry_items.lock().unwrap().len() <= 1);
}

#[tokio::test]
async fn terminal_setup_status_closes_mux_without_processing_items() {
    let (addr, streams, items) =
        spawn_recording_stub_server(ServerBehavior::AlwaysInvalidArgument).await;
    let ctx = make_ctx(&[addr], 1, Duration::from_secs(5)).await;
    let evt = build_event(1);

    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("closed mux must surface as unhandled error");

    let msg = format!("{err}");
    assert!(
        msg.contains("exhausted"),
        "expected exhaustion after closed stream, got: {msg}"
    );
    assert!(items.lock().unwrap().is_empty());
    assert_eq!(streams.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn caller_deadline_on_slow_item_surfaces_without_local_fallback() {
    let (slow_addr, _) = spawn_stub_server(ServerBehavior::HappyDelayed {
        delay: Duration::from_millis(400),
    })
    .await;
    let ctx = make_ctx(&[slow_addr], 1, Duration::from_millis(100)).await;
    let evt = build_event(1);

    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("shared item deadline must surface");
    assert!(
        format!("{err}").contains("deadline"),
        "expected deadline error, got: {err}"
    );
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
    assert!(
        hits.lock().unwrap().is_empty(),
        "setup-level Unavailable should fail before any items are processed"
    );
}
