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

/// The "unexpected error" channel — the Rust equivalent of a thrown exception
/// in the Node framework. A step returning `Err(StepError)` signals an
/// unrecoverable, non-per-event failure: in the consumer profile this fails the
/// whole batch (process exits, Kafka redelivers). Expected per-event failures
/// use `Drop`/`Dlq` verdicts instead, never this.
#[derive(Debug, thiserror::Error)]
pub enum StepError {
    /// An unexpected error that should poison the batch.
    #[error("pipeline step error: {0}")]
    Unexpected(#[from] anyhow::Error),
}

impl StepError {
    /// Build a [`StepError::Unexpected`] from any displayable message.
    pub fn msg(msg: impl Into<String>) -> Self {
        StepError::Unexpected(anyhow::anyhow!(msg.into()))
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
}
