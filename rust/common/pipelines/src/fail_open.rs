//! The `fail_open` combinator: turn a fallible step into an infallible one.
//!
//! Capture's policy philosophy is "any pre-Kafka policy step must default to
//! passing the event through on infra failure". [`FailOpen`] codifies that: it
//! wraps a step whose output type equals its input type; on `Err` (or, with
//! panic isolation, on a panic) it returns `Continue` with the **original**
//! event unchanged and increments `pipeline_step_fail_open_total{step_name}`.
//!
//! Terminal verdicts (`Drop`/`Dlq`/`Redirect`) are *not* swallowed — fail-open
//! only converts the unexpected-error channel, never a deliberate verdict.

use std::panic::AssertUnwindSafe;

use metrics::counter;

use crate::metrics_consts::STEP_FAIL_OPEN;
use crate::result::{Outputs, StepError, StepResult};
use crate::step::Step;

/// Wraps a fallible [`Step`] so it can never fail: errors (and optionally
/// panics) become a pass-through of the original event.
pub struct FailOpen<S> {
    inner: S,
    catch_panics: bool,
}

impl<S> FailOpen<S> {
    /// Wrap a step so `Err` results pass the event through unchanged.
    pub fn new(inner: S) -> Self {
        FailOpen {
            inner,
            catch_panics: false,
        }
    }

    /// Wrap a step so both `Err` results *and* panics pass the event through.
    ///
    /// The panicking `apply` runs under `catch_unwind` with `AssertUnwindSafe`;
    /// a panic mid-step may leave `Fx` partially mutated (POC limitation, noted
    /// in `POC_NOTES.md`).
    pub fn with_panic_isolation(inner: S) -> Self {
        FailOpen {
            inner,
            catch_panics: true,
        }
    }
}

impl<S, In, Fx, O> Step<In, Fx> for FailOpen<S>
where
    S: Step<In, Fx, Out = In, Outputs = O>,
    In: Clone + Send + 'static,
    Fx: 'static,
    O: Outputs,
{
    type Out = In;
    type Outputs = O;

    fn apply(&self, event: In, fx: &mut Fx) -> Result<StepResult<In, O>, StepError> {
        let backup = event.clone();

        let applied: Result<Result<StepResult<In, O>, StepError>, ()> = if self.catch_panics {
            std::panic::catch_unwind(AssertUnwindSafe(|| self.inner.apply(event, fx)))
                .map_err(|_| ())
        } else {
            Ok(self.inner.apply(event, fx))
        };

        match applied {
            Ok(Ok(result)) => Ok(result),
            Ok(Err(error)) => {
                counter!(STEP_FAIL_OPEN, "step_name" => self.inner.name()).increment(1);
                tracing::warn!(
                    step = self.inner.name(),
                    error = %error,
                    "pipeline step failed; passing event through (fail-open)"
                );
                Ok(StepResult::Continue(backup))
            }
            Err(()) => {
                counter!(STEP_FAIL_OPEN, "step_name" => self.inner.name()).increment(1);
                tracing::warn!(
                    step = self.inner.name(),
                    "pipeline step panicked; passing event through (fail-open)"
                );
                Ok(StepResult::Continue(backup))
            }
        }
    }

    fn name(&self) -> &'static str {
        self.inner.name()
    }
}

/// Ergonomic extension so a step can be wrapped with `.fail_open()`.
pub trait FailOpenExt: Sized {
    /// Wrap `self` so errors pass the event through unchanged.
    fn fail_open(self) -> FailOpen<Self> {
        FailOpen::new(self)
    }

    /// Wrap `self` so errors *and* panics pass the event through unchanged.
    fn fail_open_isolated(self) -> FailOpen<Self> {
        FailOpen::with_panic_isolation(self)
    }
}

impl<S> FailOpenExt for S {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::result::NoOutputs;

    // A step that always returns an unexpected error.
    struct AlwaysErrors;
    impl Step<i32, ()> for AlwaysErrors {
        type Out = i32;
        type Outputs = NoOutputs;
        fn apply(
            &self,
            _event: i32,
            _fx: &mut (),
        ) -> Result<StepResult<i32, NoOutputs>, StepError> {
            Err(StepError::msg("redis down"))
        }
        fn name(&self) -> &'static str {
            "always_errors"
        }
    }

    // A step that panics.
    struct AlwaysPanics;
    impl Step<i32, ()> for AlwaysPanics {
        type Out = i32;
        type Outputs = NoOutputs;
        fn apply(
            &self,
            _event: i32,
            _fx: &mut (),
        ) -> Result<StepResult<i32, NoOutputs>, StepError> {
            panic!("boom")
        }
        fn name(&self) -> &'static str {
            "always_panics"
        }
    }

    // A step that deliberately drops — fail-open must not swallow this.
    struct AlwaysDrops;
    impl Step<i32, ()> for AlwaysDrops {
        type Out = i32;
        type Outputs = NoOutputs;
        fn apply(
            &self,
            _event: i32,
            _fx: &mut (),
        ) -> Result<StepResult<i32, NoOutputs>, StepError> {
            Ok(StepResult::drop("deliberate"))
        }
        fn name(&self) -> &'static str {
            "always_drops"
        }
    }

    fn assert_continue(result: StepResult<i32, NoOutputs>, expected: i32) {
        match result {
            StepResult::Continue(v) => assert_eq!(v, expected),
            other => panic!("expected Continue({expected}), got {other:?}"),
        }
    }

    #[test]
    fn error_passes_event_through() {
        let step = AlwaysErrors.fail_open();
        let out = step.apply(7, &mut ()).unwrap();
        assert_continue(out, 7);
    }

    #[test]
    fn panic_passes_event_through_when_isolated() {
        let step = AlwaysPanics.fail_open_isolated();
        let out = step.apply(9, &mut ()).unwrap();
        assert_continue(out, 9);
    }

    #[test]
    fn deliberate_verdict_is_not_swallowed() {
        let step = AlwaysDrops.fail_open();
        let out = step.apply(3, &mut ()).unwrap();
        match out {
            StepResult::Drop { reason } => assert_eq!(reason, "deliberate"),
            other => panic!("expected Drop, got {other:?}"),
        }
    }

    #[test]
    fn fail_open_preserves_step_name() {
        let step = AlwaysErrors.fail_open();
        assert_eq!(Step::name(&step), "always_errors");
    }

    #[test]
    fn fail_open_increments_metric() {
        let recorder = metrics_util::debugging::DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        metrics::with_local_recorder(&recorder, || {
            let step = AlwaysErrors.fail_open();
            let passed = step.apply(1, &mut ()).unwrap();
            assert!(matches!(passed, StepResult::Continue(1)));
        });
        let snapshot = snapshotter.snapshot().into_vec();
        let found = snapshot.iter().any(|(key, _unit, _desc, value)| {
            key.key().name() == STEP_FAIL_OPEN
                && matches!(value, metrics_util::debugging::DebugValue::Counter(1))
        });
        assert!(found, "expected {STEP_FAIL_OPEN} counter = 1: {snapshot:?}");
    }
}
