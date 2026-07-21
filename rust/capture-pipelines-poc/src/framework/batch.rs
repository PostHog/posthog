//! Batch composition: fluent, one-type pipelines that fuse sync segments *and* async
//! stages — the design doc's §3.3 builder, with the async stage boundaries part of the
//! composition rather than hand-wired by a runner.
//!
//! A [`BatchPipeline`] processes a whole chunk (`Vec<In>`) into positional verdicts.
//! Three building blocks compose by value into one flat, monomorphized type — no boxes:
//!
//! - [`SyncStage`] lifts a sync [`Step`] chain (fused into one pass) into a batch stage.
//! - [`ConcurrentStage`] / [`GroupedStage`] run an [`AsyncProcessor`] via
//!   [`concurrently`] / [`concurrently_per_group`] at an explicit stage boundary.
//! - [`Then`] runs one batch pipeline, then feeds its `Continue` survivors to the next,
//!   merging results back **positionally** and short-circuiting drops/dlq/redirects.
//!
//! Every stage carries the pipeline's single output enum `O`: a stage's own outputs are
//! lifted into `O` via [`IntoOutputs`], so `Then` never has to reconcile output types —
//! both sides are already `O`. The [`BatchBuilder`] threads `O` and spells the whole
//! shape out in the built type (see [`crate::pipeline::AnalyticsPipeline`]).

use crate::framework::chain::{Chain, Identity, IntoOutputs};
use crate::framework::concurrency::{concurrently, concurrently_per_group, AsyncProcessor};
use crate::framework::result::{Outputs, StepResult};
use crate::framework::step::Step;
use std::hash::Hash;
use std::marker::PhantomData;

/// Lift a verdict's output set into the pipeline's unified output enum `O`.
fn lift_outputs<T, A, O>(result: StepResult<T, A>) -> StepResult<T, O>
where
    A: IntoOutputs<O>,
    O: Outputs,
{
    match result {
        StepResult::Continue(t) => StepResult::Continue(t),
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

/// A stage that processes a whole chunk into positional verdicts. `Out`/`Outputs` are
/// the state and output enum after this stage.
pub trait BatchPipeline<In, Fx> {
    /// The event state produced on `Continue`.
    type Out;
    /// The pipeline's unified output enum.
    type Outputs: Outputs;

    /// Process the chunk. The result is the same length as `events`, positional.
    async fn run_batch(
        &self,
        events: Vec<In>,
        fx: &mut Fx,
    ) -> Vec<StepResult<Self::Out, Self::Outputs>>;
}

/// The empty batch pipeline: passes every event through as `Continue`. Seeds the builder.
pub struct IdentityBatch<In, O>(PhantomData<fn(In) -> In>, PhantomData<O>);

impl<In, O> Default for IdentityBatch<In, O> {
    fn default() -> Self {
        IdentityBatch(PhantomData, PhantomData)
    }
}

impl<In, Fx, O: Outputs> BatchPipeline<In, Fx> for IdentityBatch<In, O> {
    type Out = In;
    type Outputs = O;

    async fn run_batch(&self, events: Vec<In>, _fx: &mut Fx) -> Vec<StepResult<In, O>> {
        events.into_iter().map(StepResult::Continue).collect()
    }
}

/// A sync [`Step`] chain lifted into a batch stage. Consecutive `.step(...)`s fuse into
/// one `S` chain, so this is a single inlined pass over the chunk.
pub struct SyncStage<S, O> {
    step: S,
    _o: PhantomData<O>,
}

impl<S, O> SyncStage<S, O> {
    /// Wrap a sync step chain as a batch stage.
    pub fn new(step: S) -> Self {
        SyncStage {
            step,
            _o: PhantomData,
        }
    }
}

impl<In, Fx, S, O> BatchPipeline<In, Fx> for SyncStage<S, O>
where
    S: Step<In, Fx>,
    S::Outputs: IntoOutputs<O>,
    O: Outputs,
{
    type Out = S::Out;
    type Outputs = O;

    async fn run_batch(&self, events: Vec<In>, fx: &mut Fx) -> Vec<StepResult<S::Out, O>> {
        events
            .into_iter()
            .map(|event| lift_outputs(self.step.apply(event, fx)))
            .collect()
    }
}

/// An async stage running an [`AsyncProcessor`] per item with bounded concurrency and
/// FIFO emission ([`concurrently`]).
pub struct ConcurrentStage<P, O> {
    processor: P,
    max_concurrency: usize,
    _o: PhantomData<O>,
}

impl<P, O> ConcurrentStage<P, O> {
    /// Wrap a processor as a per-item concurrent stage.
    pub fn new(max_concurrency: usize, processor: P) -> Self {
        ConcurrentStage {
            processor,
            max_concurrency,
            _o: PhantomData,
        }
    }
}

impl<Fx, P, O> BatchPipeline<P::In, Fx> for ConcurrentStage<P, O>
where
    P: AsyncProcessor,
    P::Outputs: IntoOutputs<O>,
    O: Outputs,
{
    type Out = P::Out;
    type Outputs = O;

    async fn run_batch(&self, events: Vec<P::In>, _fx: &mut Fx) -> Vec<StepResult<P::Out, O>> {
        concurrently(self.max_concurrency, &self.processor, events)
            .await
            .into_iter()
            .map(lift_outputs)
            .collect()
    }
}

/// An async stage grouping items by `key_fn` and running groups concurrently (bounded),
/// items in-order within a group ([`concurrently_per_group`]).
pub struct GroupedStage<F, P, O> {
    key_fn: F,
    processor: P,
    max_groups: usize,
    _o: PhantomData<O>,
}

impl<F, P, O> GroupedStage<F, P, O> {
    /// Wrap a processor as a grouped concurrent stage keyed by `key_fn`.
    pub fn new(max_groups: usize, key_fn: F, processor: P) -> Self {
        GroupedStage {
            key_fn,
            processor,
            max_groups,
            _o: PhantomData,
        }
    }
}

impl<Fx, F, K, P, O> BatchPipeline<P::In, Fx> for GroupedStage<F, P, O>
where
    F: Fn(&P::In) -> K,
    K: Eq + Hash + Clone,
    P: AsyncProcessor,
    P::Outputs: IntoOutputs<O>,
    O: Outputs,
{
    type Out = P::Out;
    type Outputs = O;

    async fn run_batch(&self, events: Vec<P::In>, _fx: &mut Fx) -> Vec<StepResult<P::Out, O>> {
        concurrently_per_group(
            self.max_groups,
            |item: &P::In| (self.key_fn)(item),
            &self.processor,
            events,
        )
        .await
        .into_iter()
        .map(lift_outputs)
        .collect()
    }
}

/// Run `A`, then feed its `Continue` survivors to `B`, merging back positionally.
/// Drops/dlq/redirects from `A` short-circuit `B`. Both sides share the output enum `O`.
pub struct Then<A, B> {
    first: A,
    second: B,
}

impl<A, B> Then<A, B> {
    /// Compose two batch pipelines sequentially.
    pub fn new(first: A, second: B) -> Self {
        Then { first, second }
    }
}

impl<In, Fx, A, B, O> BatchPipeline<In, Fx> for Then<A, B>
where
    A: BatchPipeline<In, Fx, Outputs = O>,
    B: BatchPipeline<A::Out, Fx, Outputs = O>,
    O: Outputs,
{
    type Out = B::Out;
    type Outputs = O;

    async fn run_batch(&self, events: Vec<In>, fx: &mut Fx) -> Vec<StepResult<B::Out, O>> {
        let first = self.first.run_batch(events, fx).await;

        // Split survivors (kept for `B`) from terminal verdicts (kept in place).
        let mut terminal: Vec<Option<StepResult<B::Out, O>>> = Vec::with_capacity(first.len());
        let mut survivors = Vec::new();
        let mut survivor_slot = Vec::new();
        for verdict in first {
            match verdict {
                StepResult::Continue(state) => {
                    survivor_slot.push(terminal.len());
                    terminal.push(None);
                    survivors.push(state);
                }
                StepResult::Drop { reason } => terminal.push(Some(StepResult::Drop { reason })),
                StepResult::Dlq { reason } => terminal.push(Some(StepResult::Dlq { reason })),
                StepResult::Redirect {
                    output,
                    preserve_key,
                } => terminal.push(Some(StepResult::Redirect {
                    output,
                    preserve_key,
                })),
            }
        }

        let second = self.second.run_batch(survivors, fx).await;
        for (verdict, slot) in second.into_iter().zip(survivor_slot) {
            terminal[slot] = Some(verdict);
        }

        terminal
            .into_iter()
            .map(|v| v.expect("every slot resolved"))
            .collect()
    }
}

/// A built batch pipeline: a thin handle exposing [`run_batch`](Built::run_batch) over
/// the composed [`BatchPipeline`]. The wrapped type spells out the whole shape.
pub struct Built<B> {
    pipeline: B,
}

impl<B> Built<B> {
    /// Run the whole composed pipeline over one batch.
    pub async fn run_batch<In, Fx>(
        &self,
        events: Vec<In>,
        fx: &mut Fx,
    ) -> Vec<StepResult<B::Out, B::Outputs>>
    where
        B: BatchPipeline<In, Fx>,
    {
        self.pipeline.run_batch(events, fx).await
    }

    /// The composed pipeline (for size/shape assertions).
    pub fn inner(&self) -> &B {
        &self.pipeline
    }
}

/// Fluent builder that fuses sync segments and async stages into one composed type.
///
/// `.step(...)` extends the current sync segment; `.stage(...)` / `.grouped_stage(...)`
/// close it, append an async stage, and open a fresh sync segment; `.build()` closes the
/// final segment. `O` is the pipeline's output enum, threaded through every stage.
pub struct BatchBuilder<O, Prefix, Sync> {
    prefix: Prefix,
    sync: Sync,
    _o: PhantomData<O>,
}

/// Start a batch pipeline over input `In` with output enum `O`.
pub fn batch_builder<In, O>() -> BatchBuilder<O, IdentityBatch<In, O>, Identity<In>> {
    BatchBuilder {
        prefix: IdentityBatch::default(),
        sync: Identity::default(),
        _o: PhantomData,
    }
}

impl<O, Prefix, Sync> BatchBuilder<O, Prefix, Sync> {
    /// Extend the current sync segment with one step (no bounds — checked at run).
    pub fn step<T>(self, step: T) -> BatchBuilder<O, Prefix, Chain<Sync, T>> {
        BatchBuilder {
            prefix: self.prefix,
            sync: Chain::new(self.sync, step),
            _o: PhantomData,
        }
    }

    /// Close the sync segment and append a per-item concurrent async stage.
    #[allow(clippy::type_complexity)]
    pub fn stage<P: AsyncProcessor>(
        self,
        max_concurrency: usize,
        processor: P,
    ) -> BatchBuilder<
        O,
        Then<Prefix, Then<SyncStage<Sync, O>, ConcurrentStage<P, O>>>,
        Identity<P::Out>,
    > {
        BatchBuilder {
            prefix: Then::new(
                self.prefix,
                Then::new(
                    SyncStage::new(self.sync),
                    ConcurrentStage::new(max_concurrency, processor),
                ),
            ),
            sync: Identity::default(),
            _o: PhantomData,
        }
    }

    /// Close the sync segment and append a grouped concurrent async stage.
    #[allow(clippy::type_complexity)]
    pub fn grouped_stage<F, P: AsyncProcessor>(
        self,
        max_groups: usize,
        key_fn: F,
        processor: P,
    ) -> BatchBuilder<
        O,
        Then<Prefix, Then<SyncStage<Sync, O>, GroupedStage<F, P, O>>>,
        Identity<P::Out>,
    > {
        BatchBuilder {
            prefix: Then::new(
                self.prefix,
                Then::new(
                    SyncStage::new(self.sync),
                    GroupedStage::new(max_groups, key_fn, processor),
                ),
            ),
            sync: Identity::default(),
            _o: PhantomData,
        }
    }

    /// Close the final sync segment and produce the runnable pipeline.
    pub fn build(self) -> Built<Then<Prefix, SyncStage<Sync, O>>> {
        Built {
            pipeline: Then::new(self.prefix, SyncStage::new(self.sync)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::framework::result::NoOutputs;

    // ZST sync step and ZST async processor, to prove the composed pipeline (sync
    // segments AND async stages) is one flat, boxless struct.
    struct AddOne;
    impl<Fx> Step<u32, Fx> for AddOne {
        type Out = u32;
        type Outputs = NoOutputs;
        fn apply(&self, e: u32, _fx: &mut Fx) -> StepResult<u32, NoOutputs> {
            StepResult::Continue(e + 1)
        }
        fn name(&self) -> &'static str {
            "add_one"
        }
    }

    struct Double;
    impl AsyncProcessor for Double {
        type In = u32;
        type Out = u32;
        type Outputs = NoOutputs;
        async fn process(&self, item: u32) -> StepResult<u32, NoOutputs> {
            StepResult::Continue(item * 2)
        }
        fn name(&self) -> &'static str {
            "double"
        }
    }

    #[test]
    fn composed_pipeline_with_async_stage_is_a_flat_struct() {
        let pipeline = batch_builder::<u32, NoOutputs>()
            .step(AddOne)
            .stage(4, Double)
            .step(AddOne)
            .build();
        // The ZST sync steps and the ZST processor contribute nothing; the *only* storage
        // is the one stage's inline `max_concurrency: usize`. So the whole composed
        // pipeline — sync chains and the async stage alike — is exactly one `usize` wide,
        // proving everything is inlined by value with no per-stage box/vtable.
        assert_eq!(
            std::mem::size_of_val(&pipeline),
            std::mem::size_of::<usize>()
        );
    }

    #[tokio::test]
    async fn composed_pipeline_runs_sync_stage_sync_positionally() {
        let pipeline = batch_builder::<u32, NoOutputs>()
            .step(AddOne) // +1
            .stage(4, Double) // *2
            .step(AddOne) // +1
            .build();
        let mut fx = ();
        let out = pipeline.run_batch(vec![1, 2, 3], &mut fx).await;
        let values: Vec<u32> = out
            .into_iter()
            .map(|r| match r {
                StepResult::Continue(v) => v,
                _ => panic!("expected continue"),
            })
            .collect();
        // 1 -> 2 -> 4 -> 5 ; 2 -> 3 -> 6 -> 7 ; 3 -> 4 -> 8 -> 9
        assert_eq!(values, vec![5, 7, 9]);
    }
}
