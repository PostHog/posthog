//! The sink mechanism trait: addressed, serialized payloads in — per-event
//! results out.
//!
//! A [`Sink`] is a single backend (Kafka, S3, print, noop). It wraps an
//! already-prepared payload into its wire shape, enqueues it, and acks. It
//! reads no event metadata and makes no decision: routing happened in the
//! pipeline layer (`pipeline::resolve`), serialization in the serialization
//! layer, and target selection belongs to the outputs layer. Anything that
//! *picks between* sinks is an output policy, not a sink.
//!
//! Health gating is deliberately not on this trait: the Kafka mechanism
//! reports liveness through its rdkafka stats callback (see `KafkaContext`),
//! and failover over unhealthy targets is an outputs-layer policy.

use async_trait::async_trait;
use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::pipeline::Address;

/// A serialized, addressed, ready-to-publish payload plus the correlation
/// UUID of the event it came from. Everything above the sink is already
/// decided: the payload bytes (serialization layer), the address and
/// partition key (lane decision), and the headers. The address is abstract on
/// purpose — each sink realizes it in its own namespace (Kafka: a topic via
/// its per-cluster table; S3: an object path; print/noop: trivially), so the
/// same payload can be handed to any target of a failover pair.
#[derive(Debug, Clone)]
pub struct AddressedPayload {
    pub uuid: Uuid,
    pub address: Address,
    pub payload: Vec<u8>,
    pub headers: CapturedEventHeaders,
    pub key: Option<String>,
}

/// Classification of a single publish attempt; lets a caller reason about
/// retriability without re-inspecting the concrete [`CaptureError`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Success,
    Retriable,
    Fatal,
}

/// Per-event result of a publish attempt, keyed by the originating event UUID.
///
/// Granularity note: the Kafka mechanism is fail-fast to preserve v0's
/// whole-request semantics, so today it reports batch-uniform results (all ok,
/// or all carrying the batch's error). The per-event surface exists so the
/// outputs layer folds results uniformly across backends and policies; it
/// refines to true per-event outcomes only when the per-event response model
/// is adopted.
pub struct SinkResult {
    pub uuid: Uuid,
    pub result: Result<(), CaptureError>,
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
    /// error is fatal (matches the request-scoped mapping callers collapse to).
    pub fn outcome(&self) -> Outcome {
        match &self.result {
            Ok(()) => Outcome::Success,
            Err(CaptureError::RetryableSinkError) => Outcome::Retriable,
            Err(_) => Outcome::Fatal,
        }
    }
}

/// The sink mechanism: publish an already-prepared batch, one [`SinkResult`]
/// per payload attempted. The batch is *consumed* (owned `Vec`) so the
/// mechanism can move each payload straight into its producer without
/// re-encoding. Sinks make no routing decisions — the address is decided
/// upstream and never second-guessed — but each sink owns realizing that
/// address within its backend's namespace.
#[async_trait]
pub trait Sink: Send + Sync {
    async fn publish(&self, prepared: Vec<AddressedPayload>) -> Vec<SinkResult>;

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
