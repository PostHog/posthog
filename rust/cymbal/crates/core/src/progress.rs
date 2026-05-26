//! Generic per-stage progress primitives for incremental pipeline runners.
//!
//! `StageProgressMode` describes how a single stage participates in
//! incremental execution: either it can be driven by independent item
//! sub-batches, or it must see the full current batch before downstream
//! stages can make progress. `PipelineEventState<T, StageId>` is a small
//! envelope tracked per item as it flows through a multi-stage pipeline:
//! it remembers the original input position, the item identifier, the
//! stage that produced the current value, and the current value itself.
//!
//! Both types are framework-level: they make no assumptions about a
//! specific domain (exception events, stage graph, etc.). Per-product
//! pipelines define their own stage IDs and combine per-stage progress
//! modes into a stage-graph capability struct (e.g. the exception
//! pipeline's `CymbalStageProgress`).

/// How a stage participates in incremental pipeline execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StageProgressMode {
    /// The stage can process independent item sub-batches. Remote executors may
    /// still group route-compatible items inside each sub-batch.
    ItemProgress,
    /// The stage must see the full current batch before downstream progress.
    BatchBarrier,
}

/// Per-item state tracked by incremental pipeline runners.
///
/// `current_stage` is generic so each pipeline can pick the stage-ID type
/// that best models its stage graph (typically a small `enum`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PipelineEventState<T, StageId> {
    pub input_index: usize,
    pub event_id: String,
    pub current_stage: StageId,
    pub item: T,
}

impl<T, StageId> PipelineEventState<T, StageId> {
    pub fn advance<NextStageId>(
        self,
        current_stage: NextStageId,
    ) -> PipelineEventState<T, NextStageId> {
        PipelineEventState {
            input_index: self.input_index,
            event_id: self.event_id,
            current_stage,
            item: self.item,
        }
    }

    pub fn map_item<U>(self, item: U) -> PipelineEventState<U, StageId> {
        PipelineEventState {
            input_index: self.input_index,
            event_id: self.event_id,
            current_stage: self.current_stage,
            item,
        }
    }
}
