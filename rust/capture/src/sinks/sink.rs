//! Per-event publish results — the vocabulary every sink reports in.
use uuid::Uuid;

use crate::api::CaptureError;

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
