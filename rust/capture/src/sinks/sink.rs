//! The sink mechanism contract: publish already-prepared payloads, report
//! per-event results.
//!
//! A sink is a single backend (Kafka today; S3, print, noop join with the
//! outputs layer). It receives [`PreparedPayload`]s — serialized, addressed,
//! headers stamped — and turns them into wire records. It reads no event
//! metadata and makes no routing decision; anything that picks between
//! backends is an output policy, not a sink.
//!
//! [`Sink::publish`] is infallible at the call level: every input payload gets
//! a [`SinkResult`], and failures travel inside them. Callers that need the
//! v0 whole-request response collapse the results with [`fold_results`].

use async_trait::async_trait;
use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::ordering::OrderingGuarantee;

/// A serialized, addressed record ready for a backend: the sink input.
/// The uuid identifies the source event so per-event results can be
/// reported without the sink ever seeing event metadata.
///
/// The fields are backend-agnostic: each sink interprets them in its own
/// terms, and nothing here names a Kafka concept. Kept field-for-field in
/// sync with `v1::sinks::types::PreparedEvent`, the shape the two stacks
/// converge on.
#[derive(Debug, Clone)]
pub(crate) struct PreparedPayload {
    pub uuid: Uuid,
    /// Realized namespace within the backend: a Kafka topic, an S3 prefix.
    /// Namespace realization happens above the sink.
    pub destination: String,
    /// Raw key; whether the sink uses it is decided by `ordering`.
    pub partition_key: String,
    /// The guarantee `partition_key` exists to preserve.
    /// [`OrderingGuarantee::None`] means publish without a key.
    pub ordering: OrderingGuarantee,
    pub payload: Vec<u8>,
    pub headers: CapturedEventHeaders,
}

/// What happened to one published payload.
#[derive(Debug)]
pub(crate) enum Outcome {
    Published,
    Failed(CaptureError),
}

/// Per-event publish result, correlated to the input by uuid.
///
/// The sink treats the uuid as pass-through: results align with the input
/// payloads by position, and nothing in the sink assumes uuids are unique
/// within a batch (v0 accepts client-supplied uuids unchecked). It is
/// carried anyway so a result is attributable to its event without the
/// caller holding the input list, which makes the per-event response model
/// (steps 19d and 20 of `rust/capture/OUTPUTS_REFACTOR_PLAN.md`) a
/// caller-side change instead of a trait change. Until that model lands,
/// `fold_results` is the only consumer and ignores it; drop this note when
/// the uuid gains its consumer.
#[derive(Debug)]
pub(crate) struct SinkResult {
    // Unread outside tests until the per-event response model consumes it;
    // see the doc comment above.
    #[allow(dead_code)]
    pub uuid: Uuid,
    pub outcome: Outcome,
}

impl SinkResult {
    pub(crate) fn published(uuid: Uuid) -> Self {
        Self {
            uuid,
            outcome: Outcome::Published,
        }
    }

    pub(crate) fn failed(uuid: Uuid, err: CaptureError) -> Self {
        Self {
            uuid,
            outcome: Outcome::Failed(err),
        }
    }
}

/// Backend mechanism: enqueue prepared payloads, ack them, report results.
/// No prepare on the trait — payload assembly belongs to the layers above.
#[async_trait]
pub(crate) trait Sink {
    async fn publish(&self, payloads: Vec<PreparedPayload>) -> Vec<SinkResult>;

    /// Flush any buffered/pending data before shutdown.
    fn flush(&self) -> Result<(), anyhow::Error>;
}

/// Collapse per-event results into the v0 whole-request response:
/// the first failure in publish order wins.
pub(crate) fn fold_results(results: Vec<SinkResult>) -> Result<(), CaptureError> {
    for result in results {
        if let Outcome::Failed(err) = result.outcome {
            return Err(err);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fold_results_empty_is_ok() {
        assert!(fold_results(vec![]).is_ok());
    }

    #[test]
    fn fold_results_all_published_is_ok() {
        let results = vec![
            SinkResult::published(Uuid::now_v7()),
            SinkResult::published(Uuid::now_v7()),
        ];
        assert!(fold_results(results).is_ok());
    }

    #[test]
    fn fold_results_first_failure_wins() {
        let results = vec![
            SinkResult::published(Uuid::now_v7()),
            SinkResult::failed(
                Uuid::now_v7(),
                CaptureError::EventTooBig("first".to_string()),
            ),
            SinkResult::failed(Uuid::now_v7(), CaptureError::RetryableSinkError),
        ];
        match fold_results(results) {
            Err(CaptureError::EventTooBig(msg)) => assert_eq!(msg, "first"),
            other => panic!("expected the first failure, got {other:?}"),
        }
    }
}
