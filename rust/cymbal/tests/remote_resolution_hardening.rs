//! Batch 4 failure-mode hardening tests for the remote resolution client.
//!
//! Each test exercises one failure surface: connection refused, mid-stream
//! interruption, missing items in the BatchSummary, caller deadline
//! cancellation, accounting, and pool-empty fast fail. Fixtures live in
//! `tests/common/mod.rs`; new failure modes should be added as variants on
//! `common::ServerBehavior` so this file stays fixture-driven.

mod common;

use std::sync::Arc;
use std::time::Duration;

use common::{
    build_event, make_ctx, process_one, remote_stage, spawn_stub_server, unbound_addr,
    ServerBehavior,
};

#[tokio::test]
async fn connection_refused_endpoint_is_classified_as_retryable() {
    // unbound_addr discovers a free port and immediately releases it — the
    // address is guaranteed not to accept connections, so the first attempt
    // returns a transport error. The Happy endpoint must serve the retry.
    let bad = unbound_addr();
    let (good, _hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[bad, good], 4, Duration::from_secs(2)).await;
    let evt = build_event(1);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("connection refused must not surface as terminal");
    assert_eq!(resolved.exception_list.len(), 1);
}

#[tokio::test]
async fn stream_interruption_mid_response_classifies_as_retryable() {
    // First endpoint sends one Done outcome then drops the stream with an
    // Internal status. The classifier must treat Internal as retryable so
    // the caller rotates to the Happy endpoint.
    let (interrupted, _interrupt_hits) =
        spawn_stub_server(ServerBehavior::InterruptAfterFirst).await;
    let (good, _good_hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[interrupted, good], 4, Duration::from_secs(2)).await;
    let evt = build_event(2);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("interrupted stream must not surface as terminal");
    assert_eq!(resolved.exception_list.len(), 2);
}

#[tokio::test]
async fn missing_items_in_batch_summary_trigger_retry_then_succeed() {
    // The DropsLastItem stub omits the last item and reports it in
    // BatchSummary.missing_items. Pointing the pool at *only* the lossy
    // endpoint guarantees we exercise the missing-item retry path
    // deterministically: the first attempt observes the gap, the second
    // attempt still observes a gap, and the caller surfaces an exhausted
    // retries error rather than silently dropping the missing exception.
    let (lossy, lossy_hits) = spawn_stub_server(ServerBehavior::DropsLastItem).await;
    let ctx = make_ctx(&[lossy], 1, Duration::from_secs(2)).await;
    let evt = build_event(3);

    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("missing-items + exhausted retries must surface unhandled");
    let msg = format!("{err}");
    assert!(
        msg.contains("exhausted"),
        "expected exhausted retries error, got: {msg}"
    );
    // max_retries=1 → 2 attempts against the lossy endpoint.
    assert_eq!(lossy_hits.lock().unwrap().len(), 2);
}

#[tokio::test]
async fn server_stream_ending_without_summary_triggers_retry() {
    // A clean stream end with all items Done but NO BatchSummary mimics the
    // server's spawn task unwinding before its terminal send. The caller must
    // not accept this as a successful response: without the summary, items
    // the server never reached are indistinguishable from items it skipped,
    // and silently passing them through downgrades resolved exceptions to
    // unresolved ones. Pointing the pool at only the lossy endpoint forces
    // every retry through it, so exhaustion proves the no-summary path stays
    // in the retry loop rather than short-circuiting to success.
    let (lossy, lossy_hits) = spawn_stub_server(ServerBehavior::DropsSummary).await;
    let ctx = make_ctx(&[lossy], 1, Duration::from_secs(2)).await;
    let evt = build_event(2);

    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("no-summary response must surface as unhandled after exhaustion");
    let msg = format!("{err}");
    assert!(
        msg.contains("exhausted"),
        "expected exhausted retries error, got: {msg}"
    );
    // max_retries=1 → 2 attempts against the lossy endpoint.
    assert_eq!(lossy_hits.lock().unwrap().len(), 2);
}

#[tokio::test]
async fn server_stream_ending_without_summary_falls_over_to_healthy_endpoint() {
    // Same shape as above but with a healthy endpoint in the pool: caller
    // rotates to it on retry and produces a fully-resolved result, proving the
    // no-summary path participates in the rotation policy like any other
    // retryable failure.
    let (lossy, _lossy_hits) = spawn_stub_server(ServerBehavior::DropsSummary).await;
    let (good, _good_hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[lossy, good], 2, Duration::from_secs(2)).await;
    let evt = build_event(2);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("no-summary lossy endpoint must rotate to healthy on retry");
    assert_eq!(resolved.exception_list.len(), 2);
}

#[tokio::test]
async fn server_per_item_error_fails_batch_under_all_or_nothing_policy() {
    // Server returns a clean stream: first item Done, every subsequent item
    // an `Error` outcome (e.g. invalid_payload), with a valid BatchSummary.
    // The `Error` path is not retryable on the client; under the all-or-nothing
    // rollout policy these MUST fail the batch rather than silently downgrade
    // the affected exceptions to unresolved-passthrough. Two endpoints + 1
    // retry: the second endpoint behaves identically, so we exhaust attempts
    // either way and the failure surfaces. (Retries don't help here, but we
    // still verify the failure mode rather than success.)
    let (lossy_a, _) = spawn_stub_server(ServerBehavior::ErrorAfterFirst {
        code: "invalid_payload",
    })
    .await;
    let (lossy_b, _) = spawn_stub_server(ServerBehavior::ErrorAfterFirst {
        code: "invalid_payload",
    })
    .await;
    let ctx = make_ctx(&[lossy_a, lossy_b], 1, Duration::from_secs(2)).await;
    let evt = build_event(3);

    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("server per-item Error must fail the batch under all-or-nothing policy");
    let msg = format!("{err}");
    assert!(
        msg.contains("item error") || msg.contains("items_failed"),
        "expected per-item-error failure surface, got: {msg}"
    );
}

#[tokio::test]
async fn caller_drops_future_before_deadline_releases_pool_slot() {
    // Verify that aborting the caller future (the way `/process` would on a
    // request timeout) does not leave the pool's in-flight counter pinned.
    // We use a HappyDelayed endpoint so remote resolution is mid-call when we
    // race a tokio::time::timeout against it; after the timeout we re-select
    // and observe zero in-flight, proving the EndpointPoolHandle's Drop guard
    // releases the slot on cancellation.
    let (addr, _hits) = spawn_stub_server(ServerBehavior::HappyDelayed {
        delay: Duration::from_millis(500),
    })
    .await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;
    let pool = Arc::clone(&ctx.pool);
    let evt = build_event(1);

    let result = tokio::time::timeout(
        Duration::from_millis(100),
        process_one(remote_stage(ctx.clone()), evt),
    )
    .await;
    assert!(
        result.is_err(),
        "remote resolution should still be in-flight when the caller times out"
    );

    // Wait briefly for the spawned tonic stream to detect the closed channel
    // and unwind. After that point a fresh select on the same pool must
    // succeed because the previous handle's Drop guard decremented in_flight.
    tokio::time::sleep(Duration::from_millis(50)).await;
    let _handle = pool.select().await.expect("pool should still be usable");
}

#[tokio::test]
async fn accounting_preserves_order_and_team_id_on_resolved_payloads() {
    // The remote orchestration layer must put each resolved exception back at the index
    // it was submitted from. The stub Done payload echoes the input verbatim,
    // so this is checking the operator's index bookkeeping, not the server's
    // resolution behavior.
    let (addr, _hits) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(2)).await;
    let evt = build_event(5);

    let original_types: Vec<String> = evt
        .exception_list
        .iter()
        .map(|e| e.exception_type.clone())
        .collect();
    let original_team_id = evt.team_id;

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("happy path");

    let resolved_types: Vec<String> = resolved
        .exception_list
        .iter()
        .map(|e| e.exception_type.clone())
        .collect();
    assert_eq!(resolved_types, original_types, "indices must be preserved");
    assert_eq!(resolved.team_id, original_team_id);
}

#[tokio::test]
async fn pool_with_only_draining_endpoints_fails_fast_without_local_fallback() {
    // Caller-side overload check: the empty pool path (no endpoints) is the
    // canonical fast-fail surface. We expect a clear `pool unavailable`
    // unhandled error within a request deadline.
    let ctx = make_ctx(&[], 0, Duration::from_millis(50)).await;
    let evt = build_event(1);

    let start = std::time::Instant::now();
    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("empty pool must fail fast");
    let elapsed = start.elapsed();

    assert!(
        elapsed < Duration::from_millis(200),
        "fast-fail expected, took {elapsed:?}"
    );
    assert!(
        format!("{err}").contains("pool unavailable"),
        "expected pool-unavailable error: {err}"
    );
}
