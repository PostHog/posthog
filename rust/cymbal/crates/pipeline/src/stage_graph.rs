//! Stage graph and per-stage metadata for Cymbal's exception pipeline.
//!
//! This module owns the static description of the pipeline's shape: which
//! stages exist, their default local implementations, the typed executor
//! bundle used by the orchestrator, per-stage progress capabilities, and the
//! per-event progress state tracked by incremental runners.
//!
//! Concerns that explicitly do not belong here: actually invoking executors,
//! streaming/ordering policy, result sinks, or transport/wire concerns.

use std::sync::Arc;

use cymbal_alerting::{AlertingEvent, AlertingStage};
use cymbal_core::{
    ContinueExecutor, LocalExecutor, PipelineStage, StageExecutor, StageProgressMode,
};
use cymbal_domain::{EventResult, InputEvent};
use cymbal_grouping::{GroupedEvent, GroupingStage};
use cymbal_linking::LinkingStage;
use cymbal_resolution::{ResolutionStage, ResolvedEvent};

use crate::IntermediateStageOutput;

pub type DefaultPipelineStages =
    PipelineStages<ResolutionStage, GroupingStage, LinkingStage, AlertingStage>;

/// The concrete stages used by the Rust-internal exception pipeline.
#[derive(Clone, Debug)]
pub struct PipelineStages<
    R = ResolutionStage,
    G = GroupingStage,
    L = LinkingStage,
    A = AlertingStage,
> {
    pub resolution: R,
    pub grouping: G,
    pub linking: L,
    pub alerting: A,
}

impl Default for DefaultPipelineStages {
    fn default() -> Self {
        Self {
            resolution: ResolutionStage::new(),
            grouping: GroupingStage::new(),
            linking: LinkingStage::new(),
            alerting: AlertingStage::new(),
        }
    }
}

/// The typed executor bundle used by the single exception-pipeline orchestrator.
#[derive(Clone)]
pub struct PipelineExecutors {
    pub resolution: Arc<dyn StageExecutor<InputEvent, IntermediateStageOutput<ResolvedEvent>>>,
    pub grouping: Arc<dyn StageExecutor<ResolvedEvent, IntermediateStageOutput<GroupedEvent>>>,
    pub linking: Arc<dyn StageExecutor<GroupedEvent, EventResult>>,
    pub alerting: Arc<dyn StageExecutor<AlertingEvent, EventResult>>,
}

impl PipelineExecutors {
    pub fn from_stages<R, G, L, A>(stages: PipelineStages<R, G, L, A>) -> Self
    where
        R: PipelineStage<Input = InputEvent, Output = ResolvedEvent> + Send + Sync + 'static,
        G: PipelineStage<Input = ResolvedEvent, Output = GroupedEvent> + Send + Sync + 'static,
        L: PipelineStage<Input = GroupedEvent, Output = EventResult> + Send + Sync + 'static,
        A: PipelineStage<Input = AlertingEvent, Output = EventResult> + Send + Sync + 'static,
    {
        Self {
            resolution: Arc::new(ContinueExecutor::new(LocalExecutor::new(stages.resolution))),
            grouping: Arc::new(ContinueExecutor::new(LocalExecutor::new(stages.grouping))),
            linking: Arc::new(LocalExecutor::new(stages.linking)),
            alerting: Arc::new(LocalExecutor::new(stages.alerting)),
        }
    }
}

impl Default for PipelineExecutors {
    fn default() -> Self {
        Self::from_stages(DefaultPipelineStages::default())
    }
}

/// Typed stage identifiers for Cymbal's exception pipeline progress metadata.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExceptionPipelineStage {
    Resolution,
    Grouping,
    Linking,
    Alerting,
    Terminal,
}

/// Cymbal's current stage-level progress capabilities.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CymbalStageProgress {
    pub resolution: StageProgressMode,
    pub grouping: StageProgressMode,
    pub linking: StageProgressMode,
    pub alerting: StageProgressMode,
}

impl Default for CymbalStageProgress {
    fn default() -> Self {
        Self {
            resolution: StageProgressMode::ItemProgress,
            grouping: StageProgressMode::ItemProgress,
            linking: StageProgressMode::BatchBarrier,
            alerting: StageProgressMode::BatchBarrier,
        }
    }
}
