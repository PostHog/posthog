//! The unified capture sink trait (v1-shaped).
//!
//! A [`Sink`] is pure produce mechanism: it takes an already-prepared batch
//! (serialization + lz4 envelope + routing already applied upstream) and
//! returns one [`SinkResult`] per event it attempted, keyed by the originating
//! event UUID. This is the shape the v1 `Sink` established (prepared batch in →
//! per-event results out) promoted into the shared `capture::sinks` module so
//! every pipeline can converge on one trait.
//!
//! The legacy [`Event`](super::Event) trait is a thin shim over this trait: it
//! hoists serialization out into a prepare step, calls [`Sink::publish_batch`],
//! and folds the per-event results back into today's request-scoped
//! [`CaptureError`] via [`fold_results`]. The richer per-event surface stays
//! dormant until the v1 response model is adopted (out of scope here).
//!
//! Health gating is deliberately *not* on this trait: the Kafka mechanism
//! reports liveness through its rdkafka stats callback (see `KafkaContext`),
//! and the health-gated failover wrapper is a separate `Sink` (`FallbackSink`,
//! Step 5). Keeping the mechanism trait free of health state is what lets that
//! wrapper compose over any `Sink`.

use async_trait::async_trait;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::sinks::producer::ProduceRecord;
use crate::v0_request::ProcessedEvent;

/// Classification of a single publish attempt. Mirrors the v1 `Outcome`; lets a
/// caller reason about retriability without re-inspecting the concrete
/// [`CaptureError`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Success,
    Retriable,
    Fatal,
}

/// A serialized, routed, ready-to-enqueue record plus its correlation UUID.
/// Output of the hoisted prepare step: serialization and the lz4 envelope have
/// already been applied, so a [`Sink`] is pure enqueue + ack mechanism.
#[derive(Debug, Clone)]
pub struct PreparedRecord {
    pub uuid: Uuid,
    pub record: ProduceRecord,
}

/// Per-event result of a publish attempt, keyed by the originating event UUID.
/// `result` is the mechanism's own `Result`; the [`Event`](super::Event) shim
/// folds a whole batch of these into one request-scoped [`CaptureError`] with
/// [`fold_results`].
pub struct SinkResult {
    pub uuid: Uuid,
    pub result: Result<(), CaptureError>,
}

/// Build a placeholder [`PreparedRecord`] for a sink that does not route to
/// Kafka (`print`, `noop`, `s3`). Those sinks consume the record only for its
/// `uuid` (result correlation) and, for `s3`, its `payload`; `topic` / `key` /
/// `headers` are inert. This keeps a non-Kafka sink on the unified [`Sink`]
/// trait without inventing routing it never uses.
pub fn passthrough_record(event: &ProcessedEvent, payload: Vec<u8>) -> PreparedRecord {
    PreparedRecord {
        uuid: event.event.uuid,
        record: ProduceRecord {
            topic: String::new(),
            key: None,
            payload,
            headers: event.event.to_headers(),
        },
    }
}

impl SinkResult {
    pub fn ok(uuid: Uuid) -> Self {
        Self {
            uuid,
            result: Ok(()),
        }
    }

    pub fn err(uuid: Uuid, error: CaptureError) -> Self {
        Self {
            uuid,
            result: Err(error),
        }
    }

    /// Classify this result. Only `RetryableSinkError` is retriable; every other
    /// error is fatal (matches the request-scoped mapping the shim collapses to).
    pub fn outcome(&self) -> Outcome {
        match &self.result {
            Ok(()) => Outcome::Success,
            Err(CaptureError::RetryableSinkError) => Outcome::Retriable,
            Err(_) => Outcome::Fatal,
        }
    }
}

/// The unified capture sink trait: a prepared batch in, per-event results out.
///
/// The batch is *consumed* (owned `Vec`) so the mechanism can move each payload
/// straight into the producer without re-encoding. Implementations decide their
/// own failure isolation; the Kafka mechanism is fail-fast to preserve v0's
/// whole-request semantics (see [`super::kafka`]).
#[async_trait]
pub trait Sink: Send + Sync {
    /// Turn a batch of `ProcessedEvent`s into ready-to-publish
    /// [`PreparedRecord`]s: serialization, routing, and any envelope live here,
    /// so [`publish_batch`](Sink::publish_batch) is pure enqueue mechanism. A
    /// single prep failure aborts the whole batch (v0's fail-fast guarantee).
    ///
    /// Kept on the trait — not just the Kafka mechanism — so a composite sink
    /// (e.g. [`FallbackSink`](super::FallbackSink)) can prepare a batch through
    /// its inner sink without knowing the concrete backend, and so the
    /// [`Event`](super::Event) shim is uniform across every sink.
    async fn prepare(
        &self,
        events: Vec<ProcessedEvent>,
    ) -> Result<Vec<PreparedRecord>, CaptureError>;

    /// Publish an already-prepared batch, returning one [`SinkResult`] per event
    /// the sink attempted. Events prepared upstream are always publishable, so
    /// there is no "skipped" result.
    async fn publish_batch(&self, prepared: Vec<PreparedRecord>) -> Vec<SinkResult>;

    /// Flush any buffered/pending data before shutdown. Default is a no-op.
    fn flush(&self) -> Result<(), anyhow::Error> {
        Ok(())
    }
}

/// Collapse a batch of per-event results into today's request-scoped response:
/// the first failing event's error wins, mirroring v0's fail-fast `send_batch`.
/// An all-success batch (or an empty batch) folds to `Ok(())`.
pub fn fold_results(results: Vec<SinkResult>) -> Result<(), CaptureError> {
    for r in results {
        r.result?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outcome_classifies_by_error_kind() {
        assert_eq!(SinkResult::ok(Uuid::nil()).outcome(), Outcome::Success);
        assert_eq!(
            SinkResult::err(Uuid::nil(), CaptureError::RetryableSinkError).outcome(),
            Outcome::Retriable
        );
        assert_eq!(
            SinkResult::err(Uuid::nil(), CaptureError::NonRetryableSinkError).outcome(),
            Outcome::Fatal
        );
        assert_eq!(
            SinkResult::err(Uuid::nil(), CaptureError::MissingSessionId).outcome(),
            Outcome::Fatal
        );
    }

    #[test]
    fn fold_empty_and_all_ok_is_ok() {
        assert!(fold_results(vec![]).is_ok());
        assert!(fold_results(vec![
            SinkResult::ok(Uuid::nil()),
            SinkResult::ok(Uuid::nil())
        ])
        .is_ok());
    }

    #[test]
    fn fold_returns_first_error() {
        let results = vec![
            SinkResult::ok(Uuid::nil()),
            SinkResult::err(Uuid::nil(), CaptureError::EventTooBig("big".to_string())),
            SinkResult::err(Uuid::nil(), CaptureError::RetryableSinkError),
        ];
        match fold_results(results) {
            Err(CaptureError::EventTooBig(_)) => {}
            other => panic!("expected first error (EventTooBig), got {other:?}"),
        }
    }
}
