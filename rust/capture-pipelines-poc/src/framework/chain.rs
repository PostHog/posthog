//! Monomorphized composition: [`Chain`], the typestate [`PipelineBuilder`], and the
//! [`Pipeline`] runner.
//!
//! Composition is **static dispatch only**. `Chain<A, B>` is a plain struct holding
//! its two steps by value; chaining `n` steps produces one nested
//! `Chain<Chain<…>, …>` type that monomorphizes into a single inlined function over
//! the event — no `Box<dyn Step>`, no vtables, no per-event allocation. The nested
//! type is verbose, but it is the visible proof that the whole pipeline is one flat
//! struct (see the `static_dispatch_is_a_flat_struct` test).
//!
//! ## Unifying outputs across a chain
//!
//! Two adjacent steps may declare different [`Outputs`] enums (e.g. an early step
//! with [`NoOutputs`] followed by one that can redirect to `AnalyticsOutputs`). The
//! chain unifies on the *downstream* step's output set and lifts the upstream one
//! into it via [`IntoOutputs`]. The only non-trivial lift in practice is
//! `NoOutputs → O` (free, because `NoOutputs` is uninhabited); a concrete enum lifts
//! into itself via a one-line identity impl. This is the simplest scheme that
//! composes the demo pipeline without type gymnastics.

use crate::framework::result::{NoOutputs, Outputs, StepResult};
use crate::framework::step::Step;
use std::marker::PhantomData;

/// Lift one output set into another when composing a chain.
///
/// Implemented blanket-style for [`NoOutputs`] (which lifts into anything), and as a
/// one-line identity impl for each concrete output enum (see
/// [`AnalyticsOutputs`](crate::pipeline::outputs::AnalyticsOutputs)). There is
/// deliberately no reflexive blanket
/// `impl<O> IntoOutputs<O> for O` — it would overlap the `NoOutputs` impl and break
/// coherence.
pub trait IntoOutputs<O: Outputs>: Outputs {
    /// Convert `self` into the unified output set.
    fn into_outputs(self) -> O;
}

impl<O: Outputs> IntoOutputs<O> for NoOutputs {
    fn into_outputs(self) -> O {
        // Unreachable: `NoOutputs` has no inhabitants, so a `Redirect` carrying one
        // can never be constructed in the first place.
        match self {}
    }
}

/// The identity step: passes every event through unchanged. Zero-sized; it seeds a
/// fresh [`PipelineBuilder`] so the first `.step(...)` has something to chain onto.
pub struct Identity<In>(PhantomData<fn(In) -> In>);

impl<In> Default for Identity<In> {
    fn default() -> Self {
        Identity(PhantomData)
    }
}

impl<In, Fx> Step<In, Fx> for Identity<In> {
    type Out = In;
    type Outputs = NoOutputs;

    fn apply(&self, event: In, _fx: &mut Fx) -> StepResult<In, NoOutputs> {
        StepResult::Continue(event)
    }

    fn name(&self) -> &'static str {
        "identity"
    }
}

/// Two steps fused into one. `A` runs first; on `Continue` its output feeds `B`.
/// Non-continue verdicts short-circuit (a `Redirect` from `A` is lifted into `B`'s
/// output set).
pub struct Chain<A, B> {
    a: A,
    b: B,
}

impl<A, B> Chain<A, B> {
    /// Construct a chain directly (the builder does this for you).
    pub fn new(a: A, b: B) -> Self {
        Chain { a, b }
    }
}

impl<In, Fx, A, B> Step<In, Fx> for Chain<A, B>
where
    A: Step<In, Fx>,
    B: Step<A::Out, Fx>,
    A::Outputs: IntoOutputs<B::Outputs>,
{
    type Out = B::Out;
    type Outputs = B::Outputs;

    fn apply(&self, event: In, fx: &mut Fx) -> StepResult<B::Out, B::Outputs> {
        match self.a.apply(event, fx) {
            StepResult::Continue(mid) => self.b.apply(mid, fx),
            StepResult::Drop { reason } => StepResult::Drop { reason },
            StepResult::Dlq { reason } => StepResult::Dlq { reason },
            StepResult::Redirect {
                output,
                preserve_key,
            } => StepResult::Redirect {
                output: output.into_outputs(),
                preserve_key,
            },
        }
    }

    fn name(&self) -> &'static str {
        // The chain reports the last step; per-step names are surfaced by observers.
        self.b.name()
    }
}

/// Typestate builder. Each `.step(...)` returns a *new concrete builder type*
/// (`PipelineBuilder<Chain<S, T>>`), so the composed step type is built up in the
/// type system as you go and monomorphizes fully at `.build()`.
pub struct PipelineBuilder<S> {
    chain: S,
}

/// Start a builder for a pipeline whose input is `In`.
pub fn builder<In>() -> PipelineBuilder<Identity<In>> {
    PipelineBuilder {
        chain: Identity::default(),
    }
}

impl<S> PipelineBuilder<S> {
    /// Append a step. No bounds are required here — the [`Step`] bounds are checked
    /// when the resulting chain is actually run against a concrete `Fx`, keeping the
    /// builder itself maximally reusable.
    pub fn step<T>(self, step: T) -> PipelineBuilder<Chain<S, T>> {
        PipelineBuilder {
            chain: Chain::new(self.chain, step),
        }
    }

    /// Finish building, producing the runnable [`Pipeline`].
    pub fn build(self) -> Pipeline<S> {
        Pipeline { chain: self.chain }
    }
}

/// A built pipeline: a thin wrapper over the composed step chain, exposing per-event
/// and per-chunk sync execution.
pub struct Pipeline<S> {
    chain: S,
}

impl<S> Pipeline<S> {
    /// Run the sync chain over one event.
    pub fn run_one<In, Fx>(&self, event: In, fx: &mut Fx) -> StepResult<S::Out, S::Outputs>
    where
        S: Step<In, Fx>,
    {
        self.chain.apply(event, fx)
    }

    /// Run the sync chain over a chunk, preserving order (verdict `i` corresponds to
    /// input `i`).
    pub fn run_chunk<In, Fx>(
        &self,
        events: Vec<In>,
        fx: &mut Fx,
    ) -> Vec<StepResult<S::Out, S::Outputs>>
    where
        S: Step<In, Fx>,
    {
        events
            .into_iter()
            .map(|e| self.chain.apply(e, fx))
            .collect()
    }

    /// Access the composed chain (used by the async runner to fuse a sync segment
    /// with a chunk stage).
    pub fn chain(&self) -> &S {
        &self.chain
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Two zero-sized demo steps, enough to prove composition is a flat struct.
    struct A;
    struct B;

    impl<Fx> Step<u32, Fx> for A {
        type Out = u32;
        type Outputs = NoOutputs;
        fn apply(&self, event: u32, _fx: &mut Fx) -> StepResult<u32, NoOutputs> {
            StepResult::Continue(event + 1)
        }
        fn name(&self) -> &'static str {
            "a"
        }
    }

    impl<Fx> Step<u32, Fx> for B {
        type Out = u32;
        type Outputs = NoOutputs;
        fn apply(&self, event: u32, _fx: &mut Fx) -> StepResult<u32, NoOutputs> {
            if event > 100 {
                StepResult::Drop { reason: "too_big" }
            } else {
                StepResult::Continue(event * 2)
            }
        }
        fn name(&self) -> &'static str {
            "b"
        }
    }

    #[test]
    fn static_dispatch_is_a_flat_struct() {
        let pipeline = builder::<u32>().step(A).step(B).build();

        // The spelled-out type: no `Box`, no `dyn` — one nested struct. If a `Box`
        // had crept in anywhere, this annotation would not type-check.
        let _typed: &Pipeline<Chain<Chain<Identity<u32>, A>, B>> = &pipeline;

        // A boxed pipeline would be pointer-sized; a flat struct of ZSTs is zero-sized.
        assert_eq!(std::mem::size_of_val(&pipeline), 0);
    }

    #[test]
    fn chain_threads_continue_and_short_circuits() {
        let pipeline = builder::<u32>().step(A).step(B).build();
        let mut fx = ();

        // 1 -> A(+1)=2 -> B(*2)=4
        match pipeline.run_one(1u32, &mut fx) {
            StepResult::Continue(v) => assert_eq!(v, 4),
            _ => panic!("expected continue"),
        }

        // 200 -> A=201 -> B drops (>100)
        assert!(matches!(
            pipeline.run_one(200u32, &mut fx),
            StepResult::Drop { reason: "too_big" }
        ));
    }

    #[test]
    fn run_chunk_preserves_order() {
        let pipeline = builder::<u32>().step(A).build();
        let mut fx = ();
        let out = pipeline.run_chunk(vec![1, 2, 3], &mut fx);
        let vals: Vec<u32> = out.into_iter().map(|r| r.continued().unwrap()).collect();
        assert_eq!(vals, vec![2, 3, 4]);
    }
}
