//! Branch and redirect names are strings, so Node's compile-time coverage checks run at run time, and an unknown branch is a DLQ.

use std::collections::HashMap;
use std::hash::Hash;
use std::sync::Arc;

use futures::FutureExt;

pub use crate::per_element::per_element;

use crate::batching::{
    AfterBatchInput, AfterBatchOutput, BatchingPipeline, BatchingPipelineOptions, BeforeBatchInput,
    BeforeBatchOutput, WithBatch,
};
use crate::branching::BranchingPipeline;
use crate::chunk_pipeline::{
    apply_chunk_step_to_results, BaseChunkPipeline, BufferingChunkPipeline, DynChunkPipeline,
    GatheringChunkPipeline, SequentialChunkPipeline,
};
use crate::concurrent::ConcurrentChunkProcessingPipeline;
use crate::context::ChunkResults;
use crate::fan_out_fan_in::{
    FanInFunction, FanOutFanInChunkPipeline, FanOutFunction, FanOutSubContext,
};
use crate::filter_map::{FilterMapChunkPipeline, FilterMapMappingFunction};
use crate::grouping::{
    process_group_chunk_sequentially, ConcurrentlyGroupingChunkPipeline, GroupChunkProcessor,
};
use crate::outputs::{HasMessage, HasTeamId};
use crate::pipeline::{DynPipeline, StartPipeline, StepPipeline};
use crate::result_handling::{PipelineConfig, ResultHandlingPipeline};
use crate::retry::{with_chunk_retry, with_step_retry, RetryOptions};
use crate::side_effect_handling::{
    SideEffectHandlingConfig, SideEffectHandlingPipeline, SideEffectHandlingProcessor,
};
use crate::side_effects::SideEffectScheduler;
use crate::steps::{ChunkProcessingStep, ProcessingStep};
use crate::timeout_barrier::TimeoutBarrierPipeline;
use crate::warning_handling::{IngestionWarningEmitter, IngestionWarningHandlingChunkPipeline};

pub struct StartPipelineBuilder<T, C> {
    _marker: std::marker::PhantomData<fn(T, C)>,
}

impl<T, C> Default for StartPipelineBuilder<T, C> {
    fn default() -> Self {
        Self {
            _marker: std::marker::PhantomData,
        }
    }
}

pub fn new_pipeline<T, C>() -> StartPipelineBuilder<T, C> {
    StartPipelineBuilder::default()
}

impl<T: Send + 'static, C: Send + 'static> StartPipelineBuilder<T, C> {
    fn start(&self) -> DynPipeline<T, T, C> {
        Arc::new(StartPipeline)
    }

    pub fn pipe<U: Send + 'static>(self, step: ProcessingStep<T, U>) -> PipelineBuilder<T, U, C> {
        PipelineBuilder::new(Arc::new(StepPipeline::new(step, self.start())))
    }

    /// Retrying passes the value again, so it must be `Clone`.
    pub fn pipe_with_retry<U: Send + 'static>(
        self,
        step: ProcessingStep<T, U>,
        retry: RetryOptions,
    ) -> PipelineBuilder<T, U, C>
    where
        T: Clone + Sync,
    {
        self.pipe(with_step_retry(step, retry))
    }

    pub fn branching<U: Send + 'static>(
        self,
        decision: impl Fn(&T) -> String + Send + Sync + 'static,
        callback: impl FnOnce(
            BranchingPipelineBuilder<T, T, U, C>,
        ) -> BranchingPipelineBuilder<T, T, U, C>,
    ) -> PipelineBuilder<T, U, C> {
        let builder = BranchingPipelineBuilder {
            decision: Arc::new(decision),
            previous: self.start(),
            branches: HashMap::new(),
        };
        PipelineBuilder::new(callback(builder).build())
    }
}

pub struct PipelineBuilder<I, O, C> {
    pipeline: DynPipeline<I, O, C>,
}

impl<I: Send + 'static, O: Send + 'static, C: Send + 'static> PipelineBuilder<I, O, C> {
    pub fn new(pipeline: DynPipeline<I, O, C>) -> Self {
        Self { pipeline }
    }

    pub fn pipe<U: Send + 'static>(self, step: ProcessingStep<O, U>) -> PipelineBuilder<I, U, C> {
        PipelineBuilder::new(Arc::new(StepPipeline::new(step, self.pipeline)))
    }

    pub fn pipe_with_retry<U: Send + 'static>(
        self,
        step: ProcessingStep<O, U>,
        retry: RetryOptions,
    ) -> PipelineBuilder<I, U, C>
    where
        O: Clone + Sync,
    {
        self.pipe(with_step_retry(step, retry))
    }

    pub fn branching<U: Send + 'static>(
        self,
        decision: impl Fn(&O) -> String + Send + Sync + 'static,
        callback: impl FnOnce(
            BranchingPipelineBuilder<I, O, U, C>,
        ) -> BranchingPipelineBuilder<I, O, U, C>,
    ) -> PipelineBuilder<I, U, C> {
        let builder = BranchingPipelineBuilder {
            decision: Arc::new(decision),
            previous: self.pipeline,
            branches: HashMap::new(),
        };
        PipelineBuilder::new(callback(builder).build())
    }

    pub fn timeout_barrier(self) -> Self {
        PipelineBuilder::new(Arc::new(TimeoutBarrierPipeline::new(self.pipeline)))
    }

    pub fn handle_side_effects(
        self,
        scheduler: Arc<dyn SideEffectScheduler>,
        config: SideEffectHandlingConfig,
    ) -> Self {
        PipelineBuilder::new(Arc::new(SideEffectHandlingProcessor::new(
            self.pipeline,
            scheduler,
            config,
        )))
    }

    pub fn build(self) -> DynPipeline<I, O, C> {
        self.pipeline
    }
}

pub struct BranchingPipelineBuilder<I, M, O, C> {
    decision: crate::branching::BranchDecisionFn<M>,
    previous: DynPipeline<I, M, C>,
    branches: HashMap<String, DynPipeline<M, O, C>>,
}

impl<I: Send + 'static, M: Send + 'static, O: Send + 'static, C: Send + 'static>
    BranchingPipelineBuilder<I, M, O, C>
{
    pub fn branch(
        mut self,
        name: &str,
        callback: impl FnOnce(StartPipelineBuilder<M, C>) -> PipelineBuilder<M, O, C>,
    ) -> Self {
        let pipeline = callback(StartPipelineBuilder::default()).build();
        self.branches.insert(name.to_string(), pipeline);
        self
    }

    pub fn build(self) -> DynPipeline<I, O, C> {
        Arc::new(BranchingPipeline::new(
            self.decision,
            self.branches,
            self.previous,
        ))
    }
}

pub fn new_chunk_pipeline<T: Send + 'static, C: Send + 'static>() -> ChunkPipelineBuilder<T, T, C, C>
{
    ChunkPipelineBuilder::new(Arc::new(BufferingChunkPipeline::<T, C>::new()))
}

pub struct ChunkPipelineBuilder<I, O, CI, CO> {
    pipeline: DynChunkPipeline<I, O, CI, CO>,
}

impl<I, O, CI, CO> ChunkPipelineBuilder<I, O, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    pub fn new(pipeline: DynChunkPipeline<I, O, CI, CO>) -> Self {
        Self { pipeline }
    }

    pub fn pipe_chunk<U: Send + 'static>(
        self,
        step: ChunkProcessingStep<O, U>,
    ) -> ChunkPipelineBuilder<I, U, CI, CO> {
        ChunkPipelineBuilder::new(Arc::new(BaseChunkPipeline::new(step, self.pipeline)))
    }

    pub fn pipe_chunk_with_retry<U: Send + 'static>(
        self,
        step: ChunkProcessingStep<O, U>,
        retry: RetryOptions,
    ) -> ChunkPipelineBuilder<I, U, CI, CO>
    where
        O: Clone + Sync,
    {
        self.pipe_chunk(with_chunk_retry(step, retry))
    }

    /// Panics on `Some(0)`, as Node's `pLimit(0)` throws.
    pub fn concurrently<U: Send + 'static>(
        self,
        callback: impl FnOnce(StartPipelineBuilder<O, CO>) -> PipelineBuilder<O, U, CO>,
        max_concurrency: Option<usize>,
    ) -> ChunkPipelineBuilder<I, U, CI, CO> {
        let processor = callback(StartPipelineBuilder::default()).build();
        ChunkPipelineBuilder::new(Arc::new(ConcurrentChunkProcessingPipeline::new(
            processor,
            self.pipeline,
            max_concurrency,
        )))
    }

    pub fn sequentially<U: Send + 'static>(
        self,
        callback: impl FnOnce(StartPipelineBuilder<O, CO>) -> PipelineBuilder<O, U, CO>,
    ) -> ChunkPipelineBuilder<I, U, CI, CO> {
        let processor = callback(StartPipelineBuilder::default()).build();
        ChunkPipelineBuilder::new(Arc::new(SequentialChunkPipeline::new(
            processor,
            self.pipeline,
        )))
    }

    pub fn gather(self) -> Self {
        ChunkPipelineBuilder::new(Arc::new(GatheringChunkPipeline::new(self.pipeline)))
    }

    pub fn filter_map<MM, U, CMM, CSO>(
        self,
        mapping: impl Fn(
                crate::context::OkResultWithContext<O, CO>,
            ) -> crate::context::OkResultWithContext<MM, CMM>
            + Send
            + Sync
            + 'static,
        sub_callback: impl FnOnce(
            ChunkPipelineBuilder<MM, MM, CMM, CMM>,
        ) -> ChunkPipelineBuilder<MM, U, CMM, CSO>,
    ) -> ChunkPipelineBuilder<I, U, CI, CSO>
    where
        MM: Send + 'static,
        U: Send + 'static,
        CMM: Send + 'static,
        CSO: From<CO> + Send + 'static,
    {
        let sub = sub_callback(new_chunk_pipeline::<MM, CMM>()).build();
        let mapping: FilterMapMappingFunction<O, MM, CO, CMM> = Arc::new(mapping);
        ChunkPipelineBuilder::new(Arc::new(FilterMapChunkPipeline::new(
            self.pipeline,
            mapping,
            sub,
        )))
    }

    pub fn fan_out<S: Send + 'static>(
        self,
        name: &str,
        fan_out: impl Fn(&O) -> Vec<S> + Send + Sync + 'static,
    ) -> FanOutBuilder<I, O, S, CI, CO> {
        FanOutBuilder {
            previous: self.pipeline,
            name: name.to_string(),
            fan_out: Arc::new(fan_out),
        }
    }

    /// Panics on `Some(0)`, as Node's `pLimit(0)` throws.
    pub fn concurrently_per_group<K, U>(
        self,
        grouping: impl Fn(&O) -> K + Send + Sync + 'static,
        callback: impl FnOnce(GroupProcessingBuilder<O, O, CO>) -> GroupProcessingBuilder<O, U, CO>,
        max_concurrency: Option<usize>,
    ) -> ChunkPipelineBuilder<I, U, CI, CO>
    where
        K: Hash + Eq + Clone + Send + Sync + 'static,
        U: Send + 'static,
    {
        let group = callback(GroupProcessingBuilder::identity());
        ChunkPipelineBuilder::new(Arc::new(ConcurrentlyGroupingChunkPipeline::new(
            Arc::new(grouping),
            group.processor,
            self.pipeline,
            max_concurrency,
        )))
    }

    pub fn handle_side_effects(
        self,
        scheduler: Arc<dyn SideEffectScheduler>,
        config: SideEffectHandlingConfig,
    ) -> Self {
        ChunkPipelineBuilder::new(Arc::new(SideEffectHandlingPipeline::new(
            self.pipeline,
            scheduler,
            config,
        )))
    }

    pub fn message_aware<U, CU>(
        self,
        callback: impl FnOnce(Self) -> ChunkPipelineBuilder<I, U, CI, CU>,
    ) -> MessageAwareChunkPipelineBuilder<I, U, CI, CU>
    where
        U: Send + 'static,
        CU: HasMessage + Send + 'static,
    {
        MessageAwareChunkPipelineBuilder {
            pipeline: callback(self).build(),
        }
    }

    pub fn team_aware<U, CU>(
        self,
        callback: impl FnOnce(Self) -> ChunkPipelineBuilder<I, U, CI, CU>,
    ) -> TeamAwareChunkPipelineBuilder<I, U, CI, CU>
    where
        U: Send + 'static,
        CU: HasTeamId + Send + 'static,
    {
        TeamAwareChunkPipelineBuilder {
            pipeline: callback(self).build(),
        }
    }

    pub fn build(self) -> DynChunkPipeline<I, O, CI, CO> {
        self.pipeline
    }
}

pub struct GroupProcessingBuilder<T, U, C> {
    processor: GroupChunkProcessor<T, U, C>,
}

impl<T: Send + 'static, C: Send + 'static> GroupProcessingBuilder<T, T, C> {
    fn identity() -> Self {
        Self {
            processor: Arc::new(|items| futures::future::ready(Ok(items)).boxed()),
        }
    }
}

impl<T: Send + 'static, U: Send + 'static, C: Send + 'static> GroupProcessingBuilder<T, U, C> {
    fn stage<V: Send + 'static>(
        self,
        next: GroupChunkProcessor<U, V, C>,
    ) -> GroupProcessingBuilder<T, V, C> {
        let first = self.processor;
        GroupProcessingBuilder {
            processor: Arc::new(move |items: ChunkResults<T, C>| {
                let first = first.clone();
                let next = next.clone();
                async move { next(first(items).await?).await }.boxed()
            }),
        }
    }

    pub fn pipe_chunk<V: Send + 'static>(
        self,
        step: ChunkProcessingStep<U, V>,
    ) -> GroupProcessingBuilder<T, V, C> {
        self.stage(Arc::new(move |items| {
            let step = step.clone();
            async move { apply_chunk_step_to_results(&step, items).await }.boxed()
        }))
    }

    pub fn sequentially<V: Send + 'static>(
        self,
        callback: impl FnOnce(StartPipelineBuilder<U, C>) -> PipelineBuilder<U, V, C>,
    ) -> GroupProcessingBuilder<T, V, C> {
        let processor = callback(StartPipelineBuilder::default()).build();
        self.stage(process_group_chunk_sequentially(processor))
    }
}

pub struct FanOutBuilder<I, O, S, CI, CO> {
    previous: DynChunkPipeline<I, O, CI, CO>,
    name: String,
    fan_out: FanOutFunction<O, S>,
}

impl<I, O, S, CI, CO> FanOutBuilder<I, O, S, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    S: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    pub fn via<SO: Send + 'static>(
        self,
        callback: impl FnOnce(
            ChunkPipelineBuilder<S, S, FanOutSubContext, FanOutSubContext>,
        )
            -> ChunkPipelineBuilder<S, SO, FanOutSubContext, FanOutSubContext>,
    ) -> FanInBuilder<I, O, S, SO, CI, CO> {
        FanInBuilder {
            previous: self.previous,
            fan_out_name: self.name,
            fan_out: self.fan_out,
            sub: callback(new_chunk_pipeline()).build(),
        }
    }
}

pub struct FanInBuilder<I, O, S, SO, CI, CO> {
    previous: DynChunkPipeline<I, O, CI, CO>,
    fan_out_name: String,
    fan_out: FanOutFunction<O, S>,
    sub: DynChunkPipeline<S, SO, FanOutSubContext, FanOutSubContext>,
}

impl<I, O, S, SO, CI, CO> FanInBuilder<I, O, S, SO, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    S: Send + 'static,
    SO: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    pub fn fan_in<U: Send + 'static>(
        self,
        name: &str,
        fan_in: impl Fn(O, Vec<SO>) -> U + Send + Sync + 'static,
    ) -> ChunkPipelineBuilder<I, U, CI, CO> {
        let fan_in: FanInFunction<O, SO, U> = Arc::new(fan_in);
        ChunkPipelineBuilder::new(Arc::new(FanOutFanInChunkPipeline::new(
            self.previous,
            &self.fan_out_name,
            self.fan_out,
            self.sub,
            name,
            fan_in,
        )))
    }
}

pub struct MessageAwareChunkPipelineBuilder<I, O, CI, CO> {
    pipeline: DynChunkPipeline<I, O, CI, CO>,
}

impl<I, O, CI, CO> MessageAwareChunkPipelineBuilder<I, O, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: HasMessage + Send + 'static,
{
    pub fn handle_results(
        self,
        config: PipelineConfig,
    ) -> ResultHandledChunkPipelineBuilder<I, O, CI, CO> {
        ResultHandledChunkPipelineBuilder {
            pipeline: Arc::new(ResultHandlingPipeline::new(self.pipeline, config)),
        }
    }
}

/// The only next step is `handle_side_effects`, so side effects are always handled before build.
pub struct ResultHandledChunkPipelineBuilder<I, O, CI, CO> {
    pipeline: DynChunkPipeline<I, O, CI, CO>,
}

impl<I, O, CI, CO> ResultHandledChunkPipelineBuilder<I, O, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
{
    pub fn handle_side_effects(
        self,
        scheduler: Arc<dyn SideEffectScheduler>,
        config: SideEffectHandlingConfig,
    ) -> ChunkPipelineBuilder<I, O, CI, CO> {
        ChunkPipelineBuilder::new(Arc::new(SideEffectHandlingPipeline::new(
            self.pipeline,
            scheduler,
            config,
        )))
    }
}

pub struct TeamAwareChunkPipelineBuilder<I, O, CI, CO> {
    pipeline: DynChunkPipeline<I, O, CI, CO>,
}

impl<I, O, CI, CO> TeamAwareChunkPipelineBuilder<I, O, CI, CO>
where
    I: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: HasTeamId + Send + 'static,
{
    pub fn handle_ingestion_warnings(
        self,
        emitter: Arc<dyn IngestionWarningEmitter>,
    ) -> ChunkPipelineBuilder<I, O, CI, CO> {
        ChunkPipelineBuilder::new(Arc::new(IngestionWarningHandlingChunkPipeline::new(
            emitter,
            self.pipeline,
        )))
    }

    pub fn into_builder(self) -> ChunkPipelineBuilder<I, O, CI, CO> {
        ChunkPipelineBuilder::new(self.pipeline)
    }
}

#[allow(clippy::type_complexity)]
pub fn new_batching_pipeline<T, O, CI, CO, CB, CF>(
    before: impl FnOnce(
        StartPipelineBuilder<BeforeBatchInput<T, CI>, ()>,
    )
        -> PipelineBuilder<BeforeBatchInput<T, CI>, BeforeBatchOutput<T, CI, CB>, ()>,
    batch: impl FnOnce(
        ChunkPipelineBuilder<WithBatch<T, CB>, WithBatch<T, CB>, CI, CI>,
    ) -> ChunkPipelineBuilder<WithBatch<T, CB>, O, CI, CO>,
    after: impl FnOnce(
        StartPipelineBuilder<AfterBatchInput<O, CO, CB>, ()>,
    )
        -> PipelineBuilder<AfterBatchInput<O, CO, CB>, AfterBatchOutput<O, CO, CB>, ()>,
    options: BatchingPipelineOptions,
) -> BatchingPipeline<T, O, CI, CO, CB, CF>
where
    T: Send + 'static,
    O: Send + 'static,
    CI: Send + 'static,
    CO: Send + 'static,
    CB: Send + Sync + 'static,
    CF: Send + 'static,
{
    let sub = batch(new_chunk_pipeline()).build();
    let before = before(StartPipelineBuilder::default()).build();
    let after = after(StartPipelineBuilder::default()).build();
    BatchingPipeline::new(sub, before, after, options)
}

pub fn before_batch_step<T, CI, CB>(
    name: &str,
    make_context: impl Fn(u64) -> CB + Send + Sync + 'static,
) -> ProcessingStep<BeforeBatchInput<T, CI>, BeforeBatchOutput<T, CI, CB>>
where
    T: Send + 'static,
    CI: Send + 'static,
    CB: Send + 'static,
{
    ProcessingStep::sync(name, move |input: BeforeBatchInput<T, CI>| {
        Ok(crate::results::ok(BeforeBatchOutput {
            batch_context: make_context(input.batch_id),
            elements: input.elements,
            batch_id: input.batch_id,
        }))
    })
}

pub fn passthrough_after_batch_step<O, CO, CB>(
    name: &str,
) -> ProcessingStep<AfterBatchInput<O, CO, CB>, AfterBatchOutput<O, CO, CB>>
where
    O: Send + 'static,
    CO: Send + 'static,
    CB: Send + Sync + 'static,
{
    ProcessingStep::sync(name, |input| Ok(crate::results::ok(input)))
}
