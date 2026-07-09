//! Hoisted, CaptureMode-agnostic serialize step.
//!
//! `serialize_batch` turns a batch of [`Event`]s into [`PreparedEvent`]s
//! (owned, storage-agnostic) before any [`Sink`](super::sink::Sink) sees them.
//! Pulling serialization out of the Sink lets every capture mode (analytics,
//! replay, AI) share one CPU-bound step and enables serialize-once /
//! fan-out-to-many-sinks for dual-write topologies.
//!
//! Small batches serialize sequentially; large batches scatter across tokio
//! tasks and gather back in input order. Per-event panics are isolated so one
//! bad event never fails the whole request.

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use tokio::task::JoinSet;
use tracing::Level;
use uuid::Uuid;

use crate::v1::constants::{
    CAPTURE_V1_SERIALIZE_DURATION_SECONDS, CAPTURE_V1_SERIALIZE_FAILED_TOTAL,
    CAPTURE_V1_SERIALIZE_PANIC_TOTAL,
};
use crate::v1::context::RequestContext;
use crate::v1::sinks::event::Event;
use crate::v1::sinks::types::{PreparedEvent, SerializationFailure, SinkResult};

/// Default scatter-gather threshold; overridden by `CAPTURE_V1_SCATTER_GATHER_MIN_BATCH`.
pub const DEFAULT_SCATTER_GATHER_MIN_BATCH: usize = 8;

/// Outcome of the serialize step: events ready to publish (input order) plus
/// per-event failures, each already a `SinkResult` so the caller can merge them
/// straight into the batch's result set.
pub struct SerializedBatch {
    pub prepared: Vec<PreparedEvent>,
    pub failures: Vec<Box<dyn SinkResult>>,
}

/// Per-event result before aggregation. `Skipped` mirrors the Sink's existing
/// behavior of silently dropping `should_publish() == false` events.
// Prepared is the hot, dominant variant and is immediately drained into a
// Vec<PreparedEvent>; boxing it just to even out variant sizes would add a
// heap allocation per successful event.
#[allow(clippy::large_enum_variant)]
enum Slot {
    Prepared(PreparedEvent),
    Skipped,
    Failed(SerializationFailure),
}

/// Serialize one event, honoring `should_publish`. Pure and panic-free at this
/// layer — panic isolation is the caller's (`run_one`) job.
fn prepare_one<E: Event>(ev: &E, ctx: &RequestContext) -> anyhow::Result<Option<PreparedEvent>> {
    if !ev.should_publish() {
        return Ok(None);
    }
    let payload = ev.serialize(ctx)?;
    Ok(Some(PreparedEvent {
        uuid: ev.uuid(),
        destination: ev.destination().clone(),
        payload,
        headers: ev.headers(ctx),
        partition_key: ev.partition_key(ctx),
    }))
}

/// Run `prepare_one` with panic isolation so a single misbehaving event (e.g. a
/// `serialize` impl that panics) is recorded as a failure instead of aborting
/// the batch / poisoning the worker.
fn run_one<E: Event>(ev: &E, ctx: &RequestContext) -> Slot {
    let uuid = ev.uuid();
    match catch_unwind(AssertUnwindSafe(|| prepare_one(ev, ctx))) {
        Ok(Ok(Some(prepared))) => Slot::Prepared(prepared),
        Ok(Ok(None)) => Slot::Skipped,
        Ok(Err(e)) => Slot::Failed(SerializationFailure::from_error(uuid, format!("{e:#}"))),
        Err(_) => Slot::Failed(SerializationFailure::panicked(uuid)),
    }
}

/// Serialize a whole batch into `PreparedEvent`s, preserving input order for
/// the prepared events so downstream per-partition ordering is unaffected.
///
/// Consumes `events` so the parallel path can share them across tokio tasks
/// via `Arc`, then hands ownership back (alongside the results) so the caller
/// can keep correlating results to events and build its response. `ctx` is
/// cloned once and shared across tasks.
pub async fn serialize_batch<E>(
    events: Vec<E>,
    ctx: &RequestContext,
    scatter_gather_threshold: usize,
) -> (Vec<E>, SerializedBatch)
where
    E: Event + 'static,
{
    let start = Instant::now();
    let n = events.len();

    // 0 disables fanout entirely (e.g. replay's single large consolidated event).
    let (events, slots): (Vec<E>, Vec<Slot>) = if scatter_gather_threshold == 0
        || n < scatter_gather_threshold
    {
        let slots = events.iter().map(|ev| run_one(ev, ctx)).collect();
        (events, slots)
    } else {
        let uuids: Vec<Uuid> = events.iter().map(|ev| ev.uuid()).collect();
        let events = Arc::new(events);
        let ctx = Arc::new(ctx.clone());
        let mut set: JoinSet<(usize, Slot)> = JoinSet::new();
        for i in 0..n {
            let events = Arc::clone(&events);
            let ctx = Arc::clone(&ctx);
            // Spawn onto the async runtime workers (not spawn_blocking): the
            // per-event work is short CPU, so concurrent execution is naturally
            // bounded by worker_threads (~num_cpus) and excess events queue
            // cheaply. This mirrors v0's send_batch and avoids saturating the
            // shared spawn_blocking pool on huge batches.
            set.spawn(async move { (i, run_one(&events[i], &ctx)) });
        }

        // Gather out-of-completion-order results back into input order.
        let mut indexed: Vec<Option<Slot>> = (0..n).map(|_| None).collect();
        while let Some(joined) = set.join_next().await {
            // run_one catches panics internally, so a JoinError is unexpected;
            // leave that slot empty and let the fill below record it as a panic.
            if let Ok((i, slot)) = joined {
                indexed[i] = Some(slot);
            }
        }
        let slots = indexed
            .into_iter()
            .enumerate()
            .map(|(i, slot)| slot.unwrap_or(Slot::Failed(SerializationFailure::panicked(uuids[i]))))
            .collect();
        // Every worker has been joined, so all worker Arc clones are dropped and
        // this is the sole owner — recover the Vec to hand back to the caller.
        let events = Arc::try_unwrap(events)
            .unwrap_or_else(|_| unreachable!("serialize workers outlived their join"));
        (events, slots)
    };

    let mut prepared = Vec::with_capacity(n);
    let mut failures: Vec<Box<dyn SinkResult>> = Vec::new();
    let mut failed_count = 0u64;
    let mut panic_count = 0u64;
    for slot in slots {
        match slot {
            Slot::Prepared(p) => prepared.push(p),
            Slot::Skipped => {}
            Slot::Failed(f) => {
                if f.is_panic() {
                    crate::ctx_log!(Level::ERROR, ctx,
                        event_uuid = %f.uuid(),
                        "event serialization panicked, dropping event"
                    );
                    panic_count += 1;
                } else {
                    crate::ctx_log!(Level::ERROR, ctx,
                        event_uuid = %f.uuid(),
                        error = %f.detail_str(),
                        "event serialization failed, dropping event"
                    );
                    failed_count += 1;
                }
                failures.push(Box::new(f));
            }
        }
    }

    histogram!(CAPTURE_V1_SERIALIZE_DURATION_SECONDS, "batch_size" => batch_size_bucket(n))
        .record(start.elapsed().as_secs_f64());
    if failed_count > 0 {
        counter!(CAPTURE_V1_SERIALIZE_FAILED_TOTAL).increment(failed_count);
    }
    if panic_count > 0 {
        counter!(CAPTURE_V1_SERIALIZE_PANIC_TOTAL).increment(panic_count);
    }

    (events, SerializedBatch { prepared, failures })
}

/// Low-cardinality batch-size bucket for the serialize-duration histogram.
fn batch_size_bucket(n: usize) -> &'static str {
    match n {
        0..=1 => "1",
        2..=8 => "2-8",
        9..=32 => "9-32",
        33..=128 => "33-128",
        _ => "129+",
    }
}

#[cfg(test)]
mod tests {
    use common_types::CapturedEventHeaders;
    use rstest::rstest;

    use super::*;
    use crate::v1::sinks::types::{Destination, Outcome};
    use crate::v1::test_utils::test_context;

    fn empty_captured_headers() -> CapturedEventHeaders {
        CapturedEventHeaders {
            token: None,
            distinct_id: None,
            session_id: None,
            timestamp: None,
            event: None,
            uuid: None,
            now: None,
            force_disable_person_processing: None,
            historical_migration: None,
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_timestamp: None,
            dlq_step: None,
            content_encoding: None,
        }
    }

    enum Behavior {
        Ok(Vec<u8>),
        Err,
        Panic,
    }

    struct FakeEvent {
        uuid: Uuid,
        publish: bool,
        destination: Destination,
        partition_key: String,
        behavior: Behavior,
    }

    impl FakeEvent {
        fn ok(payload: &str, key: &str) -> Self {
            Self {
                uuid: Uuid::new_v4(),
                publish: true,
                destination: Destination::AnalyticsMain,
                partition_key: key.to_string(),
                behavior: Behavior::Ok(payload.as_bytes().to_vec()),
            }
        }

        fn with_behavior(mut self, behavior: Behavior) -> Self {
            self.behavior = behavior;
            self
        }

        fn not_publishable(mut self) -> Self {
            self.publish = false;
            self
        }
    }

    impl Event for FakeEvent {
        fn uuid(&self) -> Uuid {
            self.uuid
        }

        fn should_publish(&self) -> bool {
            self.publish
        }

        fn destination(&self) -> &Destination {
            &self.destination
        }

        fn headers(&self, _ctx: &RequestContext) -> CapturedEventHeaders {
            empty_captured_headers()
        }

        fn partition_key(&self, _ctx: &RequestContext) -> String {
            self.partition_key.clone()
        }

        fn serialize(&self, _ctx: &RequestContext) -> anyhow::Result<bytes::Bytes> {
            match &self.behavior {
                Behavior::Ok(bytes) => Ok(bytes::Bytes::from(bytes.clone())),
                Behavior::Err => Err(anyhow::anyhow!("boom")),
                Behavior::Panic => panic!("serialize panic"),
            }
        }
    }

    /// Build `n` happy-path events whose payloads encode their input index, so
    /// ordering can be asserted regardless of the seq vs parallel path taken.
    fn ordered_events(n: usize) -> Vec<FakeEvent> {
        (0..n)
            .map(|i| FakeEvent::ok(&format!("payload-{i}"), &format!("key-{i}")))
            .collect()
    }

    /// Parity + ordering across the sequential (<8) and parallel (>=8) paths:
    /// every prepared event must come back in input order with its own payload.
    #[rstest]
    #[case::sequential_small(1)]
    #[case::sequential_boundary(7)]
    #[case::parallel_boundary(8)]
    #[case::parallel_large(64)]
    #[tokio::test]
    async fn preserves_order_and_payloads(#[case] n: usize) {
        let ctx = test_context();
        let (events, out) =
            serialize_batch(ordered_events(n), &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        assert_eq!(events.len(), n, "events must be handed back intact");
        assert_eq!(out.prepared.len(), n);
        assert!(out.failures.is_empty());
        for (i, prepared) in out.prepared.iter().enumerate() {
            assert_eq!(prepared.payload.as_ref(), format!("payload-{i}").as_bytes());
            assert_eq!(prepared.partition_key, format!("key-{i}"));
            assert_eq!(prepared.destination, Destination::AnalyticsMain);
        }
    }

    #[rstest]
    #[case::sequential(3)]
    #[case::parallel(16)]
    #[tokio::test]
    async fn skips_non_publishable_without_failure(#[case] n: usize) {
        let ctx = test_context();
        let mut events = ordered_events(n);
        events[1] = FakeEvent::ok("ignored", "key-1").not_publishable();

        let (returned, out) = serialize_batch(events, &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        assert_eq!(returned.len(), n, "all events handed back intact");
        assert_eq!(out.prepared.len(), n - 1);
        assert!(out.failures.is_empty());
        // Payloads preserve input order, skipping index 1.
        let mut expected_idx = 0;
        for prepared in &out.prepared {
            if expected_idx == 1 {
                expected_idx += 1;
            }
            assert_eq!(
                prepared.payload.as_ref(),
                format!("payload-{expected_idx}").as_bytes()
            );
            expected_idx += 1;
        }
    }

    /// A serialize error is isolated: the good events still come through and the
    /// failure surfaces as a fatal, non-retriable `SinkResult`.
    #[rstest]
    #[case::sequential(3)]
    #[case::parallel(16)]
    #[tokio::test]
    async fn serialize_error_isolated(#[case] n: usize) {
        let ctx = test_context();
        let mut events = ordered_events(n);
        let bad_uuid = events[1].uuid;
        events[1] = FakeEvent::ok("ignored", "key-1").with_behavior(Behavior::Err);
        events[1].uuid = bad_uuid;

        let (events, out) = serialize_batch(events, &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        assert_eq!(events.len(), n);
        assert_eq!(out.prepared.len(), n - 1);
        assert_eq!(out.failures.len(), 1);
        let failure = &out.failures[0];
        assert_eq!(failure.key(), bad_uuid);
        assert_eq!(failure.outcome(), Outcome::FatalError);
        assert_eq!(failure.cause(), Some("serialization_failed"));
        assert!(failure.elapsed().is_none());
    }

    /// A panicking `serialize` is caught: the rest of the batch is unaffected
    /// and the panic is reported as its own failure cause.
    #[rstest]
    #[case::sequential(3)]
    #[case::parallel(16)]
    #[tokio::test]
    async fn serialize_panic_isolated(#[case] n: usize) {
        let ctx = test_context();
        let mut events = ordered_events(n);
        events[2] = FakeEvent::ok("ignored", "key-2").with_behavior(Behavior::Panic);

        let (events, out) = serialize_batch(events, &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        assert_eq!(events.len(), n);
        assert_eq!(out.prepared.len(), n - 1);
        assert_eq!(out.failures.len(), 1);
        assert_eq!(out.failures[0].cause(), Some("serialization_panic"));
        assert_eq!(out.failures[0].outcome(), Outcome::FatalError);
    }

    /// Panic failures preserve the correct event UUID (not nil).
    #[rstest]
    #[case::sequential(3)]
    #[case::parallel(16)]
    #[tokio::test]
    async fn panic_failure_preserves_uuid(#[case] n: usize) {
        let ctx = test_context();
        let mut events = ordered_events(n);
        let panic_uuid = events[1].uuid;
        events[1] = FakeEvent::ok("ignored", "key-1").with_behavior(Behavior::Panic);
        events[1].uuid = panic_uuid;

        let (_events, out) = serialize_batch(events, &ctx, DEFAULT_SCATTER_GATHER_MIN_BATCH).await;

        assert_eq!(out.failures.len(), 1);
        assert_eq!(out.failures[0].key(), panic_uuid);
        assert_eq!(out.failures[0].cause(), Some("serialization_panic"));
    }

    #[tokio::test]
    async fn empty_batch_is_empty() {
        let ctx = test_context();
        let (events, out) = serialize_batch(
            Vec::<FakeEvent>::new(),
            &ctx,
            DEFAULT_SCATTER_GATHER_MIN_BATCH,
        )
        .await;
        assert!(events.is_empty());
        assert!(out.prepared.is_empty());
        assert!(out.failures.is_empty());
    }

    #[tokio::test]
    async fn threshold_zero_forces_sequential_for_large_batch() {
        let ctx = test_context();
        let (events, out) = serialize_batch(ordered_events(64), &ctx, 0).await;
        assert_eq!(events.len(), 64);
        assert_eq!(out.prepared.len(), 64);
        assert!(out.failures.is_empty());
    }

    #[tokio::test]
    async fn custom_threshold_boundary() {
        let ctx = test_context();
        let (_, below) = serialize_batch(ordered_events(63), &ctx, 64).await;
        let (_, at) = serialize_batch(ordered_events(64), &ctx, 64).await;
        assert_eq!(below.prepared.len(), 63);
        assert_eq!(at.prepared.len(), 64);
    }

    #[test]
    fn batch_size_bucket_boundaries() {
        assert_eq!(batch_size_bucket(0), "1");
        assert_eq!(batch_size_bucket(1), "1");
        assert_eq!(batch_size_bucket(2), "2-8");
        assert_eq!(batch_size_bucket(8), "2-8");
        assert_eq!(batch_size_bucket(9), "9-32");
        assert_eq!(batch_size_bucket(32), "9-32");
        assert_eq!(batch_size_bucket(33), "33-128");
        assert_eq!(batch_size_bucket(128), "33-128");
        assert_eq!(batch_size_bucket(129), "129+");
    }
}
