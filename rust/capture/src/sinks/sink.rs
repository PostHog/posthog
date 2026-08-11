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
use uuid::Uuid;

use crate::api::CaptureError;
use crate::sinks::producer::ProduceRecord;

/// A serialized, addressed record ready for a backend: the sink input.
/// The uuid identifies the source event so per-event results can be
/// reported without the sink ever seeing event metadata.
#[derive(Debug, Clone)]
pub struct PreparedPayload {
    pub uuid: Uuid,
    pub record: ProduceRecord,
}

/// What happened to one published payload.
#[derive(Debug)]
pub enum Outcome {
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
/// a caller-side change instead of a trait change. Until that model lands,
/// `fold_results` is the only consumer and ignores it.
#[derive(Debug)]
pub struct SinkResult {
    pub uuid: Uuid,
    pub outcome: Outcome,
}

impl SinkResult {
    pub fn published(uuid: Uuid) -> Self {
        Self {
            uuid,
            outcome: Outcome::Published,
        }
    }

    pub fn failed(uuid: Uuid, err: CaptureError) -> Self {
        Self {
            uuid,
            outcome: Outcome::Failed(err),
        }
    }
}

/// Backend mechanism: enqueue prepared payloads, ack them, report results.
/// No prepare on the trait — payload assembly belongs to the layers above.
#[async_trait]
pub trait Sink {
    async fn publish(&self, payloads: Vec<PreparedPayload>) -> Vec<SinkResult>;

    /// Flush any buffered/pending data before shutdown.
    fn flush(&self) -> Result<(), anyhow::Error>;
}

/// Batch-uniform failure: every payload in the batch reports the same error.
/// The per-event surface refines only with the per-event response model —
/// until then a batch fails or succeeds as one.
pub(crate) fn batch_failure(uuids: Vec<Uuid>, err: CaptureError) -> Vec<SinkResult> {
    uuids
        .into_iter()
        .map(|uuid| SinkResult::failed(uuid, err.clone()))
        .collect()
}

/// Collapse per-event results into the v0 whole-request response:
/// the first failure in publish order wins.
pub fn fold_results(results: Vec<SinkResult>) -> Result<(), CaptureError> {
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

    #[test]
    fn batch_failure_reports_every_uuid() {
        let uuids = vec![Uuid::now_v7(), Uuid::now_v7(), Uuid::now_v7()];
        let results = batch_failure(uuids.clone(), CaptureError::RetryableSinkError);
        assert_eq!(results.len(), uuids.len());
        for (result, uuid) in results.iter().zip(&uuids) {
            assert_eq!(result.uuid, *uuid);
            assert!(matches!(
                result.outcome,
                Outcome::Failed(CaptureError::RetryableSinkError)
            ));
        }
    }
}
