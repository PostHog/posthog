//! `retry`: wrap a [`FallibleStep`] so transient errors are retried, with an injectable
//! backoff hook.
//!
//! Mirrors Node's `withStepRetry`. The backoff is a plain `Fn(u32)` called with the
//! attempt number between tries — injectable so tests pass a no-op recorder (no real
//! sleeping) while production passes a sleeping/backoff policy. Retrying re-runs the
//! step with the same input, so the input must be [`Clone`]. The result is still a
//! [`FallibleStep`] (it can exhaust its tries), so it composes with `fail_open()`.

use crate::framework::result::StepResult;
use crate::framework::step::FallibleStep;

/// Retries a fallible step up to `tries` times, invoking `backoff(attempt)` between
/// attempts.
pub struct Retry<S, B> {
    inner: S,
    tries: u32,
    backoff: B,
}

impl<S, B> Retry<S, B> {
    /// Wrap `inner` to retry up to `tries` times (`tries >= 1`). Prefer the
    /// [`retry`](RetryExt::retry) extension method.
    pub fn new(inner: S, tries: u32, backoff: B) -> Self {
        assert!(tries >= 1, "retry needs at least one attempt");
        Retry {
            inner,
            tries,
            backoff,
        }
    }
}

impl<In, Fx, S, B> FallibleStep<In, Fx> for Retry<S, B>
where
    In: Clone,
    S: FallibleStep<In, Fx>,
    B: Fn(u32),
{
    type Out = S::Out;
    type Outputs = S::Outputs;
    type Error = S::Error;

    fn apply(
        &self,
        event: In,
        fx: &mut Fx,
    ) -> Result<StepResult<Self::Out, Self::Outputs>, Self::Error> {
        let mut attempt = 1;
        loop {
            match self.inner.apply(event.clone(), fx) {
                Ok(result) => return Ok(result),
                Err(err) => {
                    if attempt >= self.tries {
                        return Err(err);
                    }
                    (self.backoff)(attempt); // injectable; tests pass a no-op recorder
                    attempt += 1;
                }
            }
        }
    }

    fn name(&self) -> &'static str {
        self.inner.name()
    }
}

/// Extension trait adding `.retry(tries, backoff)` to any [`FallibleStep`].
pub trait RetryExt<In, Fx>: FallibleStep<In, Fx> + Sized {
    /// Wrap this step to retry up to `tries` times with the given backoff hook.
    fn retry<B: Fn(u32)>(self, tries: u32, backoff: B) -> Retry<Self, B> {
        Retry::new(self, tries, backoff)
    }
}

impl<In, Fx, S> RetryExt<In, Fx> for S where S: FallibleStep<In, Fx> {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::framework::result::NoOutputs;
    use std::cell::Cell;

    // Fails its first `fail_times` calls, then succeeds. Counts total invocations.
    struct FlakyThenOk {
        fail_times: Cell<u32>,
        calls: Cell<u32>,
    }

    impl<Fx> FallibleStep<i64, Fx> for FlakyThenOk {
        type Out = i64;
        type Outputs = NoOutputs;
        type Error = &'static str;
        fn apply(
            &self,
            event: i64,
            _fx: &mut Fx,
        ) -> Result<StepResult<i64, NoOutputs>, &'static str> {
            self.calls.set(self.calls.get() + 1);
            if self.fail_times.get() > 0 {
                self.fail_times.set(self.fail_times.get() - 1);
                return Err("transient");
            }
            Ok(StepResult::Continue(event))
        }
        fn name(&self) -> &'static str {
            "flaky"
        }
    }

    #[test]
    fn retries_until_success_recording_backoff_attempts() {
        let backoff_calls: Cell<Vec<u32>> = Cell::new(Vec::new());
        let step = FlakyThenOk {
            fail_times: Cell::new(2),
            calls: Cell::new(0),
        };
        let retried = RetryExt::<i64, ()>::retry(step, 3, |attempt| {
            let mut v = backoff_calls.take();
            v.push(attempt);
            backoff_calls.set(v);
        });

        let mut fx = ();
        let r = FallibleStep::apply(&retried, 7, &mut fx);
        assert!(matches!(r, Ok(StepResult::Continue(7))));
        // Fails twice then succeeds: 3 applies, backoff called for attempts 1 and 2.
        assert_eq!(backoff_calls.take(), vec![1, 2]);
    }

    #[test]
    fn exhausts_tries_then_returns_the_error() {
        let step = FlakyThenOk {
            fail_times: Cell::new(10), // always fails within our try budget
            calls: Cell::new(0),
        };
        let calls_seen = Cell::new(0u32);
        let retried = RetryExt::<i64, ()>::retry(step, 2, |_| {
            calls_seen.set(calls_seen.get() + 1);
        });
        let mut fx = ();
        let r = FallibleStep::apply(&retried, 1, &mut fx);
        assert!(matches!(r, Err("transient")));
        // 2 attempts, one backoff between them.
        assert_eq!(calls_seen.get(), 1);
    }
}
