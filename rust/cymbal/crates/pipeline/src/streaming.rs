//! Incremental (streaming) execution of Cymbal's exception pipeline.
//!
//! This module owns the output-order policy, the streaming configuration
//! (`StreamingPipelineOptions`), and the orchestrator that drives stages with
//! item-level progress and emits per-event outcomes through a generic
//! `OrderedEmitter` over an [`EventResultSink`].
//!
//! Concerns that explicitly do not belong here: stage execution, the
//! generic ordered-emission mechanics, pure ordering utilities, or the
//! buffered batch pipeline entry point. Those live in
//! [`cymbal_core::executor`], [`cymbal_core::emission`], [`crate::ordering`],
//! and [`crate`] respectively.
//!
//! The buffered batch path now delegates to `cymbal_core::LinearPipelineRunner`
//! through `crate::runner`. This streaming path intentionally keeps its custom
//! orchestration until the generic runner supports the existing resolution +
//! grouping item-progress chunking/concurrency semantics.

use std::collections::HashMap;
use std::sync::Arc;

use cymbal_core::{BatchContext, EmissionOrder, OrderedEmitter, StageError, StageProgressMode};
use cymbal_domain::{EventResult, InputEvent};
use cymbal_grouping::GroupedEvent;
use futures::StreamExt;

use crate::ordering::{
    event_result_to_alerting_event, sort_by_input_order, split_intermediate_outputs,
    split_rate_limit_outputs,
};
use crate::sink::EventResultSink;
use crate::stage_graph::{CymbalStageProgress, PipelineExecutors};

/// Whether final event outcomes may be emitted as soon as they complete or
/// must preserve the public input order.
///
/// This is the exception-pipeline-facing alias for [`EmissionOrder`]; the
/// streaming orchestrator converts to the generic enum before constructing
/// the [`OrderedEmitter`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PipelineOutputOrder {
    /// Preserve the existing `ProcessExceptionBatch` input-order contract.
    InputOrder,
    /// Emit each final outcome immediately after it is safe for that event.
    CompletionOrder,
}

impl From<PipelineOutputOrder> for EmissionOrder {
    fn from(order: PipelineOutputOrder) -> Self {
        match order {
            PipelineOutputOrder::InputOrder => EmissionOrder::InputOrder,
            PipelineOutputOrder::CompletionOrder => EmissionOrder::CompletionOrder,
        }
    }
}

/// Backpressure and ordering controls for incremental pipeline execution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StreamingPipelineOptions {
    pub output_order: PipelineOutputOrder,
    pub item_progress_chunk_size: usize,
    pub max_concurrent_item_progress_chunks: usize,
    pub stage_progress: CymbalStageProgress,
}

impl Default for StreamingPipelineOptions {
    fn default() -> Self {
        Self {
            output_order: PipelineOutputOrder::InputOrder,
            item_progress_chunk_size: 64,
            max_concurrent_item_progress_chunks: 8,
            stage_progress: CymbalStageProgress::default(),
        }
    }
}

pub async fn process_exception_pipeline_streaming<Sink>(
    context: Arc<BatchContext>,
    input_events: Vec<InputEvent>,
    executors: &PipelineExecutors,
    options: StreamingPipelineOptions,
    sink: Sink,
) -> Result<(), StageError>
where
    Sink: EventResultSink,
{
    let input_event_ids = input_events
        .iter()
        .map(|event| event.event_id.clone())
        .collect::<Vec<_>>();
    let input_index_by_event_id = input_event_ids
        .iter()
        .enumerate()
        .map(|(index, event_id)| (event_id.clone(), index))
        .collect::<HashMap<_, _>>();
    let mut emitter =
        OrderedEmitter::for_identified(input_event_ids, options.output_order.into(), sink);

    let rate_limited = executors
        .rate_limiting
        .run(context.clone(), input_events)
        .await?;
    let (allowed_events, rate_limit_terminal_results) = split_rate_limit_outputs(rate_limited);
    emitter.emit_many(rate_limit_terminal_results).await?;

    let grouped = if options.stage_progress.resolution == StageProgressMode::ItemProgress
        && options.stage_progress.grouping == StageProgressMode::ItemProgress
    {
        run_item_progress_resolution_and_grouping(
            context.clone(),
            allowed_events,
            executors,
            options.item_progress_chunk_size,
            options.max_concurrent_item_progress_chunks,
            &mut emitter,
        )
        .await?
    } else {
        let resolved = executors
            .resolution
            .run(context.clone(), allowed_events)
            .await?;
        let (resolved, resolution_failures) = split_intermediate_outputs(resolved);
        emitter.emit_many(resolution_failures).await?;

        let grouped = executors.grouping.run(context.clone(), resolved).await?;
        let (grouped, grouping_failures) = split_intermediate_outputs(grouped);
        emitter.emit_many(grouping_failures).await?;
        grouped
    };

    let grouped = sort_by_input_order(grouped, &input_index_by_event_id, |event| &event.event_id);

    let linked = executors.linking.run(context.clone(), grouped).await?;
    let alerting_events = linked
        .into_iter()
        .map(event_result_to_alerting_event)
        .collect::<Vec<_>>();
    emitter
        .emit_many(executors.alerting.run(context, alerting_events).await?)
        .await?;
    emitter.finish()
}

async fn run_item_progress_resolution_and_grouping<Sink, IdFn>(
    context: Arc<BatchContext>,
    allowed_events: Vec<InputEvent>,
    executors: &PipelineExecutors,
    chunk_size: usize,
    max_concurrent_chunks: usize,
    emitter: &mut OrderedEmitter<EventResult, Sink, IdFn>,
) -> Result<Vec<GroupedEvent>, StageError>
where
    Sink: EventResultSink,
    IdFn: Fn(&EventResult) -> &str + Send,
{
    let chunk_size = chunk_size.max(1);
    let max_concurrent_chunks = max_concurrent_chunks.max(1);
    let chunks = allowed_events
        .chunks(chunk_size)
        .map(|chunk| chunk.to_vec())
        .collect::<Vec<_>>();

    let mut grouped_events = Vec::new();
    let mut chunk_stream = futures::stream::iter(chunks.into_iter().map(|chunk| {
        let context = context.clone();
        async move { run_resolution_and_grouping_chunk(context, chunk, executors).await }
    }))
    .buffer_unordered(max_concurrent_chunks);

    while let Some(chunk_result) = chunk_stream.next().await {
        let ItemProgressChunkOutput { grouped, terminal } = chunk_result?;
        emitter.emit_many(terminal).await?;
        grouped_events.extend(grouped);
    }

    Ok(grouped_events)
}

struct ItemProgressChunkOutput {
    grouped: Vec<GroupedEvent>,
    terminal: Vec<EventResult>,
}

async fn run_resolution_and_grouping_chunk(
    context: Arc<BatchContext>,
    input_events: Vec<InputEvent>,
    executors: &PipelineExecutors,
) -> Result<ItemProgressChunkOutput, StageError> {
    let resolved = executors
        .resolution
        .run(context.clone(), input_events)
        .await?;
    let (resolved, resolution_failures) = split_intermediate_outputs(resolved);

    let grouped = executors.grouping.run(context, resolved).await?;
    let (grouped, grouping_failures) = split_intermediate_outputs(grouped);
    let mut terminal = resolution_failures;
    terminal.extend(grouping_failures);

    Ok(ItemProgressChunkOutput { grouped, terminal })
}
