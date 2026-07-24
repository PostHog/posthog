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
//! both sides are already `O`. The [`BatchBuilder`] threads `O` through every stage; the
//! composed [`Built`] type can stay opaque behind `impl BatchPipeline` at the boundary
//! (see [`crate::pipeline::build_analytics_pipeline`]).

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

/// Scoped composition builder: every stage boundary is a **nested callback**, so the
/// code shape mirrors the execution shape (the Node builder's `sequentially` /
/// `concurrently` / `concurrentlyPerGroup` closures). A run of sync steps is one
/// `sequentially(|b| b.step(..).step(..))` scope; each async stage is its own
/// scope-opening call whose per-item body is nested inside — never a flat
/// `.step()`-lookalike that hides the concurrency boundary.
///
/// `Cur` tracks the builder's current item type so a `sequentially` scope knows its
/// input. An async stage's processor carries its own input type, so async stages
/// don't need `Cur` and re-establish it as the processor's output; a `sequentially`
/// scope's output is `Step::Out` (resolved only against a concrete `Fx` at run) and
/// so is not nameable here — it [`Sealed`]s `Cur`. The next stage must therefore be an
/// async stage (its processor names the type again); two bare sync scopes back-to-back
/// should just be merged into one. Every actual input/output match across stages is
/// still enforced by the [`Then`]/[`BatchPipeline`] bounds when `run_batch` is
/// monomorphized.
pub struct Compose<O, Cur, Prefix> {
    prefix: Prefix,
    _pd: PhantomData<fn() -> (O, Cur)>,
}

/// The sealed current-type marker (see [`Compose`]). Uninhabited: it is only ever a
/// phantom type parameter, never a value.
pub enum Sealed {}

/// Start a scoped batch pipeline over input `In` with output enum `O`.
pub fn compose<In, O>() -> Compose<O, In, IdentityBatch<In, O>> {
    Compose {
        prefix: IdentityBatch::default(),
        _pd: PhantomData,
    }
}

/// Sync sub-scope handed to a [`Compose::sequentially`] callback. Chains sync steps
/// into one fused [`Chain`] (exactly like [`chain::builder`](crate::framework::chain)),
/// but as a nested scope so a run of steps reads as one unit.
pub struct SyncScope<In, S> {
    chain: S,
    _in: PhantomData<fn(In) -> In>,
}

impl<In, S> SyncScope<In, S> {
    /// Append one sync step to this scope (no bounds — checked at run).
    pub fn step<T>(self, step: T) -> SyncScope<In, Chain<S, T>> {
        SyncScope {
            chain: Chain::new(self.chain, step),
            _in: PhantomData,
        }
    }
}

/// Per-item scope handed to a [`Compose::concurrently`] callback. Its [`run`](ItemScope::run)
/// names the async processor applied to each item (bounded concurrency, FIFO emission).
pub struct ItemScope<In>(PhantomData<fn(In)>);

/// The body of an [`ItemScope`] — the processor to run per item.
pub struct ItemBody<P>(P);

impl<In> ItemScope<In> {
    /// Run `processor` on each item of the chunk, concurrently.
    pub fn run<P: AsyncProcessor>(self, processor: P) -> ItemBody<P> {
        ItemBody(processor)
    }
}

/// Per-group scope handed to a [`Compose::grouped`] callback. Its
/// [`in_order`](GroupScope::in_order) names the processor applied to each item; items
/// within a group run in input order, groups run concurrently.
pub struct GroupScope<In>(PhantomData<fn(In)>);

/// The body of a [`GroupScope`] — the processor run per item, in-order within a group.
pub struct GroupBody<P>(P);

impl<In> GroupScope<In> {
    /// Run `processor` on each item of a group, in input order (groups still run
    /// concurrently with respect to each other).
    pub fn in_order<P: AsyncProcessor>(self, processor: P) -> GroupBody<P> {
        GroupBody(processor)
    }
}

/// Builder state after a [`Compose::sequentially`] scope: a `SyncStage` appended, the
/// current type [`Sealed`] (a sync scope's `Step::Out` is not nameable here).
type SeqNext<O, Prefix, S> = Compose<O, Sealed, Then<Prefix, SyncStage<S, O>>>;
/// Builder state after a [`Compose::concurrently`] stage: current type is the
/// processor's output.
type ConcurrentNext<O, Prefix, P> =
    Compose<O, <P as AsyncProcessor>::Out, Then<Prefix, ConcurrentStage<P, O>>>;
/// Builder state after a [`Compose::grouped`] stage: current type is the processor's
/// output.
type GroupedNext<O, Prefix, KF, P> =
    Compose<O, <P as AsyncProcessor>::Out, Then<Prefix, GroupedStage<KF, P, O>>>;

impl<O: Outputs, Cur, Prefix> Compose<O, Cur, Prefix> {
    /// A sync scope: chain a run of sync steps, fused into one pass. The callback
    /// receives a fresh [`SyncScope`] over the current item type and returns it after
    /// chaining steps.
    pub fn sequentially<F, S>(self, scope: F) -> SeqNext<O, Prefix, S>
    where
        F: FnOnce(SyncScope<Cur, Identity<Cur>>) -> SyncScope<Cur, S>,
    {
        let chain = scope(SyncScope {
            chain: Identity::default(),
            _in: PhantomData,
        })
        .chain;
        Compose {
            prefix: Then::new(self.prefix, SyncStage::new(chain)),
            _pd: PhantomData,
        }
    }

    /// A per-item concurrent async stage. The callback receives an [`ItemScope`] and
    /// names the processor run on each item ([`ItemScope::run`]).
    pub fn concurrently<F, P>(
        self,
        max_concurrency: usize,
        scope: F,
    ) -> ConcurrentNext<O, Prefix, P>
    where
        F: FnOnce(ItemScope<Cur>) -> ItemBody<P>,
        P: AsyncProcessor,
    {
        let ItemBody(processor) = scope(ItemScope(PhantomData));
        Compose {
            prefix: Then::new(
                self.prefix,
                ConcurrentStage::new(max_concurrency, processor),
            ),
            _pd: PhantomData,
        }
    }

    /// A grouped concurrent async stage keyed by `key_fn`. The callback receives a
    /// [`GroupScope`] and names the processor run per item ([`GroupScope::in_order`]):
    /// items within a group run in input order, groups run concurrently.
    pub fn grouped<KF, F, P>(
        self,
        max_groups: usize,
        key_fn: KF,
        scope: F,
    ) -> GroupedNext<O, Prefix, KF, P>
    where
        F: FnOnce(GroupScope<Cur>) -> GroupBody<P>,
        P: AsyncProcessor,
    {
        let GroupBody(processor) = scope(GroupScope(PhantomData));
        Compose {
            prefix: Then::new(
                self.prefix,
                GroupedStage::new(max_groups, key_fn, processor),
            ),
            _pd: PhantomData,
        }
    }

    /// Produce the runnable pipeline.
    pub fn build(self) -> Built<Prefix> {
        Built {
            pipeline: self.prefix,
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
        let pipeline = compose::<u32, NoOutputs>()
            .sequentially(|b| b.step(AddOne))
            .concurrently(4, |item| item.run(Double))
            .sequentially(|b| b.step(AddOne))
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
        let pipeline = compose::<u32, NoOutputs>()
            .sequentially(|b| b.step(AddOne)) // +1
            .concurrently(4, |item| item.run(Double)) // *2
            .sequentially(|b| b.step(AddOne)) // +1
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
