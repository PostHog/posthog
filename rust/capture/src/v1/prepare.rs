//! The v1 serialize step.
//!
//! `serialize_batch` turns [`Publishable`] events into the outputs layer's
//! [`PreparedEvent`]s, which `OutputRegistry::publish_prepared` takes. It runs
//! before any output sees the batch, so CPU-bound encoding stays apart from
//! produce I/O and can run in parallel.
//!
//! Each event serializes under `catch_unwind`, so a panic fails only that event.

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use tokio::task::JoinSet;
use tracing::Level;
use uuid::Uuid;

use crate::outputs::PreparedEvent;
use crate::v1::constants::{
    CAPTURE_V1_SERIALIZE_DURATION_SECONDS, CAPTURE_V1_SERIALIZE_FAILED_TOTAL,
    CAPTURE_V1_SERIALIZE_PANIC_TOTAL,
};
use crate::v1::context::RequestContext;
use crate::v1::types::Publishable;

/// Batches smaller than this serialize inline, because spawning a task per
/// event costs more than serializing a handful of events. Overridden by
/// `CAPTURE_V1_SCATTER_GATHER_MIN_BATCH`.
pub const DEFAULT_SCATTER_GATHER_MIN_BATCH: usize = 8;

pub struct SerializedBatch {
    /// In input order.
    pub prepared: Vec<PreparedEvent>,
    pub failures: Vec<SerializationFailure>,
}

// Prepared is the hot, dominant variant and is immediately drained into a
// Vec<PreparedEvent>; boxing it just to even out variant sizes would add a
// heap allocation per successful event.
#[allow(clippy::large_enum_variant)]
enum Slot {
    Prepared(PreparedEvent),
    /// Not published, so it gets no result.
    Skipped,
    Failed(SerializationFailure),
}

fn prepare_one<E: Publishable>(
    ev: &E,
    ctx: &RequestContext,
) -> anyhow::Result<Option<PreparedEvent>> {
    if !ev.should_publish() {
        return Ok(None);
    }
    let Some(address) = ev.destination().address() else {
        return Ok(None);
    };
    let payload = ev.serialize(ctx)?;
    Ok(Some(PreparedEvent {
        uuid: ev.uuid(),
        address,
        payload,
        headers: ev.headers(ctx),
        partition_key: ev.partition_key(ctx),
        ordering: ev.ordering(),
    }))
}

/// Records a panic in `prepare_one` as this event's failure, so one bad event
/// cannot fail the batch or kill the worker task.
fn run_one<E: Publishable>(ev: &E, ctx: &RequestContext) -> Slot {
    let uuid = ev.uuid();
    match catch_unwind(AssertUnwindSafe(|| prepare_one(ev, ctx))) {
        Ok(Ok(Some(prepared))) => Slot::Prepared(prepared),
        Ok(Ok(None)) => Slot::Skipped,
        Ok(Err(e)) => Slot::Failed(SerializationFailure::from_error(uuid, format!("{e:#}"))),
        Err(_) => Slot::Failed(SerializationFailure::panicked(uuid)),
    }
}

/// Prepared events keep input order, so per-partition order downstream
/// matches the request.
///
/// Takes `events` by value because the parallel path shares them across
/// tasks, and returns them so the caller can build its per-event response.
pub async fn serialize_batch<E>(
    events: Vec<E>,
    ctx: &RequestContext,
    scatter_gather_threshold: usize,
) -> (Vec<E>, SerializedBatch)
where
    E: Publishable + 'static,
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
            // Spawn onto the async runtime workers, not spawn_blocking: the
            // per-event work is short CPU, so worker_threads bounds the
            // concurrency and excess events queue cheaply. One spawn_blocking
            // task per event would saturate the shared blocking pool on huge
            // batches. The Kafka sink's parallel prep does the same.
            set.spawn(async move { (i, run_one(&events[i], &ctx)) });
        }

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
    let mut failures: Vec<SerializationFailure> = Vec::new();
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
                failures.push(f);
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

/// An event that failed to serialize. Always fatal: serializing the same event
/// again fails the same way, so it is dropped, never retried.
#[derive(Debug, Clone)]
pub struct SerializationFailure {
    uuid: Uuid,
    cause: &'static str,
    detail: String,
}

impl SerializationFailure {
    pub fn from_error(uuid: Uuid, detail: String) -> Self {
        Self {
            uuid,
            cause: "serialization_failed",
            detail,
        }
    }

    pub fn panicked(uuid: Uuid) -> Self {
        Self {
            uuid,
            cause: "serialization_panic",
            detail: "serialization task panicked".to_string(),
        }
    }

    pub fn is_panic(&self) -> bool {
        self.cause == "serialization_panic"
    }

    pub fn uuid(&self) -> Uuid {
        self.uuid
    }

    pub fn cause(&self) -> &'static str {
        self.cause
    }

    pub fn detail_str(&self) -> &str {
        &self.detail
    }
}

#[cfg(test)]
mod tests {
    use common_types::CapturedEventHeaders;
    use rstest::rstest;

    use super::*;
    use crate::ordering::OrderingGuarantee;
    use crate::pipeline::{Address, Lane, Pipeline};
    use crate::v1::test_utils::test_context;
    use crate::v1::types::Destination;

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

    impl Publishable for FakeEvent {
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

        fn ordering(&self) -> OrderingGuarantee {
            OrderingGuarantee::PerDistinctId
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
            assert_eq!(
                prepared.address,
                Address::Lane {
                    pipeline: Pipeline::Analytics,
                    lane: Lane::Main
                }
            );
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
    /// failure surfaces as a `serialization_failed` failure.
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
        assert_eq!(failure.uuid(), bad_uuid);
        assert_eq!(failure.cause(), "serialization_failed");
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
        assert_eq!(out.failures[0].cause(), "serialization_panic");
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
        assert_eq!(out.failures[0].uuid(), panic_uuid);
        assert_eq!(out.failures[0].cause(), "serialization_panic");
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
