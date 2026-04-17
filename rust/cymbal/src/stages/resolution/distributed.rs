use std::{collections::HashMap, sync::Arc};

use crate::{
    app_context::AppContext,
    distributed::{
        tasks::{extract_tasks, ResolveTaskResult, TaskLocation},
        DistributedContext,
    },
    error::UnhandledError,
    frames::Frame,
    metric_consts::{DISTRIBUTED_FALLBACK_TOTAL, RESOLUTION_STAGE},
    stages::{
        pipeline::ExceptionEventPipelineItem,
        resolution::{frame::FrameResolver, properties::PropertiesResolver},
    },
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
        Stacktrace,
    },
};

#[derive(Clone)]
pub struct DistributedResolutionStage {
    context: DistributedContext,
}

impl From<&Arc<AppContext>> for DistributedResolutionStage {
    fn from(app_context: &Arc<AppContext>) -> Self {
        Self {
            context: DistributedContext::new(app_context),
        }
    }
}

impl Stage for DistributedResolutionStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

    fn name(&self) -> &'static str {
        RESOLUTION_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        let mut output: Vec<ExceptionEventPipelineItem> = Vec::from(batch);
        let mut states = collect_event_states(&output);

        if !states.is_empty() {
            let (tasks, bindings) = extract_all_tasks(&states);
            let results = self.context.resolve_tasks(tasks).await?;

            apply_results_to_states(&mut states, &bindings, results)?;
            materialize_resolved_frames(&mut states, &self.context).await?;

            for state in states {
                output[state.batch_index] = Ok(state.event);
            }
        }

        Batch::from(output)
            .apply_operator(PropertiesResolver, self.context.resolution.clone())
            .await
    }
}

// -- batch orchestration (private) --

#[derive(Debug, Clone)]
struct EventState {
    batch_index: usize,
    event: crate::types::exception_properties::ExceptionProperties,
    frame_overrides: HashMap<(usize, usize), Vec<Frame>>,
}

#[derive(Debug, Clone)]
struct TaskBinding {
    state_index: usize,
    location: TaskLocation,
}

fn collect_event_states(output: &[ExceptionEventPipelineItem]) -> Vec<EventState> {
    output
        .iter()
        .enumerate()
        .filter_map(|(batch_index, item)| {
            item.as_ref().ok().map(|event| EventState {
                batch_index,
                event: event.clone(),
                frame_overrides: HashMap::new(),
            })
        })
        .collect()
}

fn extract_all_tasks(
    states: &[EventState],
) -> (
    Vec<crate::distributed::tasks::ResolveTask>,
    HashMap<u64, TaskBinding>,
) {
    let mut tasks = Vec::new();
    let mut bindings = HashMap::new();
    let mut next_task_id: u64 = 1;

    for (state_index, state) in states.iter().enumerate() {
        for planned in extract_tasks(&state.event, &mut next_task_id) {
            bindings.insert(
                planned.task.task_id(),
                TaskBinding {
                    state_index,
                    location: planned.location,
                },
            );
            tasks.push(planned.task);
        }
    }

    (tasks, bindings)
}

fn apply_results_to_states(
    states: &mut [EventState],
    bindings: &HashMap<u64, TaskBinding>,
    results: HashMap<u64, ResolveTaskResult>,
) -> Result<(), UnhandledError> {
    for (task_id, result) in results {
        let Some(binding) = bindings.get(&task_id) else {
            continue;
        };

        let Some(state) = states.get_mut(binding.state_index) else {
            metrics::counter!(DISTRIBUTED_FALLBACK_TOTAL, "reason" => "merge_error").increment(1);
            continue;
        };

        match result {
            ResolveTaskResult::Frame { frames, .. } => {
                let Some(frame_index) = binding.location.frame_index else {
                    metrics::counter!(DISTRIBUTED_FALLBACK_TOTAL, "reason" => "merge_error")
                        .increment(1);
                    continue;
                };

                state
                    .frame_overrides
                    .insert((binding.location.exception_index, frame_index), frames);
            }
            ResolveTaskResult::JavaException {
                module,
                exception_type,
                ..
            } => {
                if let Some(exception) = state
                    .event
                    .exception_list
                    .get_mut(binding.location.exception_index)
                {
                    exception.module = module;
                    exception.exception_type = exception_type;
                } else {
                    metrics::counter!(DISTRIBUTED_FALLBACK_TOTAL, "reason" => "merge_error")
                        .increment(1);
                }
            }
            ResolveTaskResult::DartException { exception_type, .. } => {
                if let Some(exception) = state
                    .event
                    .exception_list
                    .get_mut(binding.location.exception_index)
                {
                    exception.exception_type = exception_type;
                } else {
                    metrics::counter!(DISTRIBUTED_FALLBACK_TOTAL, "reason" => "merge_error")
                        .increment(1);
                }
            }
        }
    }

    Ok(())
}

async fn materialize_resolved_frames(
    states: &mut [EventState],
    ctx: &DistributedContext,
) -> Result<(), UnhandledError> {
    for state in states.iter_mut() {
        for exception_index in 0..state.event.exception_list.len() {
            let Some(Stacktrace::Raw { frames: raw_frames }) =
                state.event.exception_list[exception_index].stack.clone()
            else {
                continue;
            };

            let mut merged_frames = Vec::new();
            let mut complete = true;

            for frame_index in 0..raw_frames.len() {
                if let Some(mut frames) = state
                    .frame_overrides
                    .remove(&(exception_index, frame_index))
                {
                    merged_frames.append(&mut frames);
                } else {
                    complete = false;
                    break;
                }
            }

            if complete {
                state.event.exception_list[exception_index].stack =
                    Some(Stacktrace::Resolved {
                        frames: merged_frames,
                    });
                continue;
            }

            metrics::counter!(DISTRIBUTED_FALLBACK_TOTAL, "reason" => "merge_error").increment(1);
            let unresolved = state.event.exception_list[exception_index].clone();
            let resolved = FrameResolver::resolve_exception_frames(
                state.event.team_id,
                unresolved,
                &state.event.debug_images,
                ctx.resolution.clone(),
            )
            .await?;
            state.event.exception_list[exception_index] = resolved;
        }
    }

    Ok(())
}
