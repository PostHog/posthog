//! The sink mechanism contract: publish already-prepared payloads, report
//! per-event results.
//!
//! A sink is a single backend (Kafka today; S3, print, noop join with the
//! outputs layer). It receives [`PreparedPayload`]s — serialized, addressed,
//! headers stamped — and turns them into wire records. It reads no event
//! metadata and makes no routing decision; anything that picks between
//! backends is an output policy, not a sink.
//!
//! [`Sink::publish`] does not return an error: every input payload gets a
//! [`SinkResult`], and a failure is reported in that payload's result. Callers
//! that need the v0 whole-request response collapse the results with
//! [`fold_results`].

use async_trait::async_trait;
use common_types::CapturedEventHeaders;
use uuid::Uuid;

use crate::api::CaptureError;
use crate::ordering::OrderingGuarantee;
use crate::sinks::registry::Destination;

/// A serialized, addressed record ready for a backend: the sink input.
/// The uuid identifies the source event so per-event results can be
/// reported without the sink ever seeing event metadata.
///
/// The fields are backend-agnostic: each sink interprets them in its own
/// terms, and nothing here names a Kafka concept.
#[derive(Debug, Clone)]
pub(crate) struct PreparedPayload {
    pub uuid: Uuid,
    /// The output this record is addressed to. Each sink resolves it to its
    /// own target, as v1's sinks resolve their `Destination`.
    pub destination: Destination,
    pub partition_key: String,
    pub ordering: OrderingGuarantee,
    pub payload: Vec<u8>,
    pub headers: CapturedEventHeaders,
}

/// What happened to one published payload.
#[derive(Debug)]
pub enum Outcome {
    Published,
    Failed(CaptureError),
}

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
pub(crate) trait Sink {
    async fn publish(&self, payloads: Vec<PreparedPayload>) -> Vec<SinkResult>;
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
