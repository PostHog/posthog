//! `fail_open`: turn a [`FallibleStep`] into an infallible [`Step`].
//!
//! This is the compile-time expression of capture's core philosophy: *any pre-Kafka
//! policy step must default to passing the event through on infra failure*. A
//! [`FallibleStep`] cannot join a capture chain; wrapping it in [`FailOpen`] converts
//! any `Err` into "continue with the original event, unchanged" plus a counter bump,
//! yielding an infallible [`Step`] the capture profile will accept.
//!
//! Because on error we must return the *original* input, [`FailOpen`] requires the
//! wrapped step to be a pure filter (`Out == In`) and the input to be [`Clone`] — we
//! keep a cheap clone as the fallback. That is the one simplification here; the real
//! framework would additionally `catch_unwind` per event for panic isolation.

use crate::framework::result::StepResult;
use crate::framework::step::{FallibleStep, Step};
use std::sync::atomic::{AtomicU64, Ordering};

/// Wraps a fallible pure-filter step, making it infallible by passing the event
/// through on error and counting the occurrence.
pub struct FailOpen<S> {
    inner: S,
    fail_open_count: AtomicU64,
}

impl<S> FailOpen<S> {
    /// Wrap a fallible step. Prefer the
    /// [`fail_open`](FallibleStepExt::fail_open) extension method.
    pub fn new(inner: S) -> Self {
        FailOpen {
            inner,
            fail_open_count: AtomicU64::new(0),
        }
    }

    /// How many times this step has failed open (the `pipeline_step_fail_open_total`
    /// counter, as a plain atomic — no metrics dependency in the POC).
    pub fn fail_open_count(&self) -> u64 {
        self.fail_open_count.load(Ordering::Relaxed)
    }
}

impl<In, Fx, S> Step<In, Fx> for FailOpen<S>
where
    In: Clone,
    S: FallibleStep<In, Fx, Out = In>,
{
    type Out = In;
    type Outputs = S::Outputs;

    fn apply(&self, event: In, fx: &mut Fx) -> StepResult<In, S::Outputs> {
        let fallback = event.clone();
        match self.inner.apply(event, fx) {
            Ok(result) => result,
            Err(_) => {
                self.fail_open_count.fetch_add(1, Ordering::Relaxed);
                StepResult::Continue(fallback)
            }
        }
    }

    fn name(&self) -> &'static str {
        self.inner.name()
    }
}

/// Extension trait providing `.fail_open()` on any [`FallibleStep`].
pub trait FallibleStepExt<In, Fx>: FallibleStep<In, Fx> + Sized {
    /// Wrap this fallible step so it fails open (see [`FailOpen`]).
    fn fail_open(self) -> FailOpen<Self> {
        FailOpen::new(self)
    }
}

impl<In, Fx, S> FallibleStepExt<In, Fx> for S where S: FallibleStep<In, Fx> {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::framework::result::NoOutputs;

    // A limiter that errors for one token (simulating Redis being down) and otherwise
    // drops "over_quota" events.
    struct FlakyLimiter {
        error_token: &'static str,
    }

    impl<Fx> FallibleStep<&'static str, Fx> for FlakyLimiter {
        type Out = &'static str;
        type Outputs = NoOutputs;
        type Error = &'static str;

        fn apply(
            &self,
            token: &'static str,
            _fx: &mut Fx,
        ) -> Result<StepResult<&'static str, NoOutputs>, &'static str> {
            if token == self.error_token {
                return Err("redis down");
            }
            if token == "over_quota" {
                return Ok(StepResult::Drop {
                    reason: "quota_limited",
                });
            }
            Ok(StepResult::Continue(token))
        }

        fn name(&self) -> &'static str {
            "flaky_limiter"
        }
    }

    #[test]
    fn erroring_step_passes_event_through_and_bumps_counter() {
        // The extension method is generic over `Fx`; annotate it here (in a real
        // pipeline `Fx` is inferred from the composed effects struct).
        let step = FallibleStepExt::<&'static str, ()>::fail_open(FlakyLimiter {
            error_token: "boom",
        });
        let mut fx = ();

        // Erroring input passes through unchanged.
        let r = Step::apply(&step, "boom", &mut fx);
        assert!(matches!(r, StepResult::Continue("boom")));
        assert_eq!(step.fail_open_count(), 1);

        // Non-erroring verdicts are preserved.
        assert!(matches!(
            Step::apply(&step, "over_quota", &mut fx),
            StepResult::Drop {
                reason: "quota_limited"
            }
        ));
        assert!(matches!(
            Step::apply(&step, "ok", &mut fx),
            StepResult::Continue("ok")
        ));
        // Counter unchanged by the non-erroring calls.
        assert_eq!(step.fail_open_count(), 1);
    }
}
