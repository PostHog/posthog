//! Core result vocabulary shared by every pipeline step.
//!
//! Every step returns one of four verdicts per event, mirroring the Node
//! framework's `ok | dlq | drop | redirect`. Reasons are `&'static str` so
//! they can be used directly as metric label values (the `details` label on
//! `ingestion_pipeline_results`).

use std::fmt;

/// The set of redirect targets a pipeline can produce, defined per pipeline.
///
/// A pipeline with no redirect targets uses [`NoOutputs`], an uninhabited enum:
/// its `Redirect` variant can never be constructed, so the compiler proves the
/// pipeline never redirects.
pub trait Outputs: Copy + Eq + fmt::Debug + 'static {
    /// Stable identifier used as a metric label and as the output-registry key.
    fn name(&self) -> &'static str;
}

/// An uninhabited [`Outputs`] implementation for pipelines that never redirect.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NoOutputs {}

impl Outputs for NoOutputs {
    fn name(&self) -> &'static str {
        // Unreachable: `NoOutputs` has no inhabitants, so no value exists to
        // call this on.
        match *self {}
    }
}

/// Per-event decision returned by a step. `T` is the (possibly enriched) event
/// state; `O` is the pipeline's redirect-target enum.
pub enum StepResult<T, O: Outputs> {
    /// The event passes through, carrying its (possibly type-changed) state.
    Continue(T),
    /// The event is dropped silently (no produce). `reason` is a metric label.
    Drop { reason: &'static str },
    /// The event is routed to the dead-letter queue. `reason` is a metric label;
    /// `error` optionally carries diagnostic context (not produced downstream).
    Dlq {
        reason: &'static str,
        error: Option<anyhow::Error>,
    },
    /// The event is redirected to one of the pipeline's typed outputs.
    /// `preserve_key` decides whether the original Kafka key is retained.
    Redirect { output: O, preserve_key: bool },
}

impl<T, O: Outputs> StepResult<T, O> {
    /// Convenience constructor for a drop verdict.
    pub fn drop(reason: &'static str) -> Self {
        StepResult::Drop { reason }
    }

    /// Convenience constructor for a DLQ verdict with no attached error.
    pub fn dlq(reason: &'static str) -> Self {
        StepResult::Dlq {
            reason,
            error: None,
        }
    }

    /// Convenience constructor for a redirect verdict.
    pub fn redirect(output: O, preserve_key: bool) -> Self {
        StepResult::Redirect {
            output,
            preserve_key,
        }
    }

    /// True for any terminal (non-`Continue`) verdict.
    pub fn is_terminal(&self) -> bool {
        !matches!(self, StepResult::Continue(_))
    }
}

impl<T: fmt::Debug, O: Outputs> fmt::Debug for StepResult<T, O> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StepResult::Continue(t) => f.debug_tuple("Continue").field(t).finish(),
            StepResult::Drop { reason } => f.debug_struct("Drop").field("reason", reason).finish(),
            StepResult::Dlq { reason, error } => f
                .debug_struct("Dlq")
                .field("reason", reason)
                .field("error", &error.as_ref().map(|e| e.to_string()))
                .finish(),
            StepResult::Redirect {
                output,
                preserve_key,
            } => f
                .debug_struct("Redirect")
                .field("output", output)
                .field("preserve_key", preserve_key)
                .finish(),
        }
    }
}

/// The non-per-event error channel of a pipeline. A step returning
/// `Err(StepError)` aborts the whole chunk; the two variants differ in what
/// that abort *means*:
///
/// - [`StepError::Unexpected`] — the Rust equivalent of a thrown exception in
///   the Node framework: an unrecoverable failure. In the consumer profile this
///   fails the whole batch (process exits, Kafka redelivers). Expected
///   per-event failures use `Drop`/`Dlq` verdicts instead, never this.
/// - [`StepError::Reject`] — a *request-level rejection* (the "gate" outcome of
///   design §3.9): an expected, policy-driven abort of the whole request, e.g.
///   a structurally invalid batch or a billing limit that rejects the request
///   with a specific HTTP status. The caller recovers its typed error with
///   [`StepError::try_into_reject`].
#[derive(Debug, thiserror::Error)]
pub enum StepError {
    /// An unexpected error that should poison the batch.
    #[error("pipeline step error: {0}")]
    Unexpected(#[from] anyhow::Error),
    /// An expected request-level rejection carrying the caller's typed error.
    #[error("request rejected: {0}")]
    Reject(anyhow::Error),
}

impl StepError {
    /// Build a [`StepError::Unexpected`] from any displayable message.
    pub fn msg(msg: impl Into<String>) -> Self {
        StepError::Unexpected(anyhow::anyhow!(msg.into()))
    }

    /// Build a [`StepError::Reject`] carrying a typed error the caller can
    /// recover with [`StepError::try_into_reject`].
    pub fn reject<E>(err: E) -> Self
    where
        E: std::error::Error + Send + Sync + 'static,
    {
        StepError::Reject(anyhow::Error::new(err))
    }

    /// If this is a [`StepError::Reject`] carrying an `E`, unwrap it; otherwise
    /// hand the error back unchanged.
    pub fn try_into_reject<E>(self) -> Result<E, Self>
    where
        E: std::error::Error + Send + Sync + 'static,
    {
        match self {
            StepError::Reject(err) => err.downcast::<E>().map_err(StepError::Reject),
            other => Err(other),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum TestOutputs {
        Overflow,
    }

    impl Outputs for TestOutputs {
        fn name(&self) -> &'static str {
            match self {
                TestOutputs::Overflow => "overflow",
            }
        }
    }

    #[test]
    fn continue_is_not_terminal() {
        let r: StepResult<u32, NoOutputs> = StepResult::Continue(5);
        assert!(!r.is_terminal());
    }

    #[test]
    fn drop_dlq_redirect_are_terminal() {
        let d: StepResult<u32, TestOutputs> = StepResult::drop("blocked_token");
        assert!(d.is_terminal());

        let q: StepResult<u32, TestOutputs> = StepResult::dlq("restricted_to_dlq");
        assert!(q.is_terminal());

        let r: StepResult<u32, TestOutputs> = StepResult::redirect(TestOutputs::Overflow, true);
        assert!(r.is_terminal());
    }

    #[test]
    fn outputs_name_is_stable() {
        assert_eq!(TestOutputs::Overflow.name(), "overflow");
    }

    #[test]
    fn redirect_carries_output_and_key_flag() {
        let r: StepResult<(), TestOutputs> = StepResult::redirect(TestOutputs::Overflow, false);
        match r {
            StepResult::Redirect {
                output,
                preserve_key,
            } => {
                assert_eq!(output, TestOutputs::Overflow);
                assert!(!preserve_key);
            }
            _ => panic!("expected redirect"),
        }
    }

    #[test]
    fn step_error_from_anyhow() {
        let e = StepError::msg("boom");
        assert!(e.to_string().contains("boom"));
    }

    #[derive(Debug, thiserror::Error, PartialEq)]
    enum CallerError {
        #[error("billing limit exceeded")]
        BillingLimit,
    }

    #[test]
    fn reject_roundtrips_typed_error() {
        let e = StepError::reject(CallerError::BillingLimit);
        assert!(e.to_string().contains("request rejected"));
        let recovered: CallerError = e.try_into_reject().expect("downcast succeeds");
        assert_eq!(recovered, CallerError::BillingLimit);
    }

    #[test]
    fn try_into_reject_passes_through_unexpected() {
        let e = StepError::msg("boom");
        let back = e.try_into_reject::<CallerError>().unwrap_err();
        assert!(matches!(back, StepError::Unexpected(_)));
    }

    #[test]
    fn try_into_reject_wrong_type_stays_reject() {
        #[derive(Debug, thiserror::Error)]
        #[error("other")]
        struct Other;

        let e = StepError::reject(Other);
        let back = e.try_into_reject::<CallerError>().unwrap_err();
        assert!(matches!(back, StepError::Reject(_)));
    }
}
