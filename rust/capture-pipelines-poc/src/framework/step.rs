//! The step traits: the workhorse [`Step`] and its fallible sibling [`FallibleStep`].
//!
//! A [`Step`] is a synchronous, per-event transform. It is *infallible by
//! construction*: its `apply` returns a [`StepResult`] directly, with no error
//! channel. This is the capture profile's core invariant — the capture pipeline
//! composes only `Step`s, so "a policy step can't block an event on an infra
//! failure" is a property the type system enforces, not a convention.
//!
//! Steps that genuinely can fail (a Redis-backed limiter, say) implement
//! [`FallibleStep`] instead, and must be wrapped with
//! [`fail_open`](crate::framework::fail_open::FallibleStepExt::fail_open) before they
//! can join an infallible chain. Fallibility is *unrepresentable* in a capture chain
//! unless it has been explicitly neutralized.

use crate::framework::result::{Outputs, StepResult};

/// A synchronous, infallible, per-event step — the framework's workhorse.
///
/// `In` is the input event state; `Out` is the (possibly enriched or type-changed)
/// output state. `Fx` is the pipeline's composed effects struct — steps constrain it
/// with capability bounds (e.g. `Fx: WarningEffects`) rather than the framework
/// hardcoding cross-cutting concerns into the event type. See [`crate::framework::fx`].
///
/// Type-changing steps (`In` → `Out`) model phase progression: a step that needs the
/// team takes `WithTeam`, one that needs only the token takes anything `HasToken`.
/// Composition order is then checked by ordinary type inference.
pub trait Step<In, Fx> {
    /// The event state this step produces on `Continue`.
    type Out;
    /// The redirect targets this step can emit (`NoOutputs` if it never redirects).
    type Outputs: Outputs;

    /// Apply the step to one event. Infallible: the only outcomes are the four
    /// [`StepResult`] verdicts.
    fn apply(&self, event: In, fx: &mut Fx) -> StepResult<Self::Out, Self::Outputs>;

    /// Stable step name — the `last_step` metric label and stack-trace anchor.
    fn name(&self) -> &'static str;
}

/// A synchronous per-event step that can fail with an *unexpected* error.
///
/// This is the Rust equivalent of a thrown exception in the Node framework: the
/// error channel is for infrastructure failures, not policy verdicts (those are
/// still `Drop`/`Dlq`/`Redirect`). A `FallibleStep` cannot join a capture chain
/// directly — it must first be wrapped by
/// [`fail_open`](crate::framework::fail_open::FallibleStepExt::fail_open), which converts any
/// `Err` into "pass the event through unchanged" plus a counter bump.
pub trait FallibleStep<In, Fx> {
    /// The event state this step produces on `Continue`.
    type Out;
    /// The redirect targets this step can emit.
    type Outputs: Outputs;
    /// The unexpected-error type (e.g. a Redis error).
    type Error;

    /// Apply the step, or fail with an unexpected error.
    fn apply(
        &self,
        event: In,
        fx: &mut Fx,
    ) -> Result<StepResult<Self::Out, Self::Outputs>, Self::Error>;

    /// Stable step name.
    fn name(&self) -> &'static str;
}
