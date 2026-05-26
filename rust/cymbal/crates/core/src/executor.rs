//! Buffered stage executors and intermediate stage output types.
//!
//! This module owns the runtime adapter between [`PipelineStage`]
//! implementations and the orchestrator: it normalizes per-stage invocations
//! through the [`StageExecutor`] trait, wraps local stages via
//! [`LocalExecutor`], and lifts continue-only stages into the
//! [`IntermediateStageOutput`] shape via [`ContinueExecutor`].
//!
//! These primitives are framework-level: they describe how a typed batch
//! pipeline routes per-item results between stages without referencing any
//! specific domain (exception events, terminal result shapes, etc.). Domain
//! composition lives in the per-product pipeline crates.
//!
//! Concerns that explicitly do not belong here: pipeline composition,
//! streaming/ordering policy, sinks, or any stage-specific business logic.

use std::sync::Arc;

use async_trait::async_trait;

use crate::{BatchContext, PipelineStage, StageError, StageInput};

/// Runs one buffered stage invocation.
#[async_trait]
pub trait StageExecutor<I, O>: Send + Sync
where
    I: Send + 'static,
    O: Send + 'static,
{
    async fn run(&self, ctx: Arc<BatchContext>, inputs: Vec<I>) -> Result<Vec<O>, StageError>;
}

/// Local [`StageExecutor`] implementation backed by a [`PipelineStage`].
#[derive(Clone, Debug)]
pub struct LocalExecutor<Stage> {
    stage: Stage,
}

impl<Stage> LocalExecutor<Stage> {
    pub fn new(stage: Stage) -> Self {
        Self { stage }
    }

    pub fn stage(&self) -> &Stage {
        &self.stage
    }
}

#[async_trait]
impl<Stage> StageExecutor<Stage::Input, Stage::Output> for LocalExecutor<Stage>
where
    Stage: PipelineStage + Send + Sync,
    Stage::Input: Send + 'static,
    Stage::Output: Send + 'static,
{
    async fn run(
        &self,
        ctx: Arc<BatchContext>,
        inputs: Vec<Stage::Input>,
    ) -> Result<Vec<Stage::Output>, StageError> {
        self.stage
            .process(StageInput::from_arc_items(ctx, inputs))
            .await
    }
}

/// Output from an intermediate pipeline stage.
///
/// `Continue` items flow into the next stage. `Terminal` results are final
/// per-item outcomes that bypass the remaining stages and are merged back
/// into the final ordered result set by the orchestrator. The terminal type
/// is generic so the framework does not depend on any one domain's result
/// shape; product pipelines pin `Terminal` to their own per-item outcome type.
///
/// `Continue` and `Terminal` variants can have very different sizes — the
/// continue path through an intermediate stage is typically the dominant
/// one, and terminal results may carry resolved data of their own. We avoid
/// boxing the dominant continue variant to keep the per-item hot path
/// allocation-free; concrete pipelines that hit the `large_enum_variant`
/// clippy lint after monomorphization can `#[allow]` it at the alias site.
#[derive(Debug, Clone, PartialEq)]
pub enum IntermediateStageOutput<T, Terminal> {
    Continue(T),
    Terminal(Terminal),
}

/// Adapts a normal executor into an intermediate executor by wrapping every
/// output item as [`IntermediateStageOutput::Continue`].
#[derive(Clone, Debug)]
pub struct ContinueExecutor<Executor> {
    inner: Executor,
}

impl<Executor> ContinueExecutor<Executor> {
    pub fn new(inner: Executor) -> Self {
        Self { inner }
    }
}

#[async_trait]
impl<I, O, Terminal, Executor> StageExecutor<I, IntermediateStageOutput<O, Terminal>>
    for ContinueExecutor<Executor>
where
    I: Send + 'static,
    O: Send + 'static,
    Terminal: Send + 'static,
    Executor: StageExecutor<I, O> + Send + Sync,
{
    async fn run(
        &self,
        ctx: Arc<BatchContext>,
        inputs: Vec<I>,
    ) -> Result<Vec<IntermediateStageOutput<O, Terminal>>, StageError> {
        Ok(self
            .inner
            .run(ctx, inputs)
            .await?
            .into_iter()
            .map(IntermediateStageOutput::Continue)
            .collect())
    }
}
