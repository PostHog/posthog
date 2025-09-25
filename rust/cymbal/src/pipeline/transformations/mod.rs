use std::{collections::HashMap, sync::Arc};

use chrono::{DateTime, Utc};
use common_types::ClickHouseEvent;
use hogvm::{ExecutionContext, Program, VmError};
use metrics::counter;
use serde_json::Value;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{PipelineFailure, PipelineResult},
    metric_consts::TRANSFORMATION_EVENTS_DROPPED,
    pipeline::transformations::types::{
        HogFunctionFilter, TransformLog, TransformOutcome, TransformResult, TransformSetOutcome,
    },
};

pub mod transform;
pub mod types;

// TODO - there's just ample room for optimization here, if anyone feels like picking it up. Ofc, take a look at the timing metrics first.

// We could, and probably should, cache these, rather than caching the raw HogFunction's
struct ExecutableHogFunction {
    id: Uuid,
    filter: Option<ExecutionContext>,
    transform: ExecutionContext,
}

pub async fn apply_transformations(
    events: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    // First, convert the hog function list for each team into an execution context list for each team
    let mut executable_lists = HashMap::new();
    for (i, event) in events.iter().enumerate() {
        let Ok(event) = event else {
            continue;
        };

        if executable_lists.contains_key(&event.team_id) {
            continue;
        }

        let functions = context
            .team_manager
            .function_manager
            .get_functions(&context.pool, event.team_id)
            .await
            .map_err(|e| (i, e))?;

        let mut executables = Vec::new();

        // We don't need to sort these, the manager returns them in the right order
        for function in functions {
            let transform_bytecode = context
                .team_manager
                .function_manager
                .get_function_bytecode(&context.pool, &function)
                .await
                .map_err(|e| (i, e))?;

            let Some(Value::Array(transform_bytecode)) = transform_bytecode else {
                context
                    .team_manager
                    .function_manager
                    .disable_function(&function, "Bytecode not found or not an array")
                    .await
                    .map_err(|e| (i, e))?;
                continue;
            };

            let transform_program = match Program::new(transform_bytecode) {
                Ok(p) => p,
                Err(e) => {
                    context
                        .team_manager
                        .function_manager
                        .disable_function(&function, &format!("Failed to create program: {}", e))
                        .await
                        .map_err(|e| (i, e))?;
                    continue;
                }
            };

            // Globals like inputs etc. Does not include the event itself, as that is overwritten each time.
            let placeholder_globals = context
                .team_manager
                .function_manager
                .get_function_globals(&function)
                .await
                .map_err(|e| (i, e))?;

            let transform_context = ExecutionContext::with_defaults(transform_program)
                .with_globals(placeholder_globals);

            let Some(filters) = &function.filters else {
                executables.push(ExecutableHogFunction {
                    id: function.id,
                    filter: None,
                    transform: transform_context,
                });
                continue;
            };

            let Ok(filters) = serde_json::from_value::<HogFunctionFilter>(filters.clone()) else {
                context
                    .team_manager
                    .function_manager
                    .disable_function(&function, "Filter not valid")
                    .await
                    .map_err(|e| (i, e))?;
                continue;
            };

            let Some(filter_bytecode) = filters.bytecode else {
                executables.push(ExecutableHogFunction {
                    id: function.id,
                    filter: None,
                    transform: transform_context,
                });
                continue;
            };

            let filter_program = match Program::new(filter_bytecode) {
                Ok(p) => p,
                Err(e) => {
                    context
                        .team_manager
                        .function_manager
                        .disable_function(&function, &format!("Filter bytecode error: {}", e))
                        .await
                        .map_err(|e| (i, e))?;
                    continue;
                }
            };

            let filter_context = ExecutionContext::with_defaults(filter_program); // Filters have no globals aside from the event

            executables.push(ExecutableHogFunction {
                id: function.id,
                filter: Some(filter_context),
                transform: transform_context,
            });
        }

        executable_lists.insert(event.team_id, executables);
    }

    // We collect these to feed back to the manager for disabling, reporting logs etc.
    // This isn't implemented yet, need to coordinate with CDP, right now they're just used for reporting metrics.
    let mut transform_results: HashMap<Uuid, Vec<TransformResult>> = HashMap::new();
    // In the future, this will be an events.iter_mut(), and then we'll *event = outcome.final_event.unwrap_or(PipelineResult::Err(EventError::DroppedByTransformation)),
    // but for now, as we're just collecting execution outcome data, we don't do that yet. This is also used to report app metrics and logs.
    for event in events.iter() {
        let Ok(event) = event else {
            continue;
        };

        let Some(list) = executable_lists.get_mut(&event.team_id) else {
            continue;
        };

        let outcome = execute_transformations(event.clone(), list);

        if let None = outcome.final_event {
            counter!(TRANSFORMATION_EVENTS_DROPPED).increment(1);
        }

        for res in outcome.results {
            transform_results
                .entry(res.function_id)
                .or_default()
                .push(res);
        }
    }

    context
        .team_manager
        .function_manager
        .process_execution_results(transform_results)
        .await
        .map_err(|e| (0, e))?; // TODO - not great here, but it's pretty hard to tie a failure here to a particular event, so :shrug:

    Ok(events)
}

// Apply a set of transformations to an event. Each transformation results in a TransformationResult.
fn execute_transformations(
    event: ClickHouseEvent,
    // TODO - this has to be mutable, because we have to mutate the ExecutionContext's contained here to install the event globals before running the filter. This is better
    // than cloning the ExecutableHogFunction for each event, but it's still pretty ugly. A better HogVM interface would let us handle the globals set more elegantly.
    function_list: &mut Vec<ExecutableHogFunction>,
) -> TransformSetOutcome {
    let mut results = Vec::new();

    let mut final_event = Some(event);

    for function in function_list.iter_mut() {
        // If the last transform dropped the event, we can exit early.
        let Some(current) = final_event.as_ref() else {
            break;
        };

        // Should we apply this transformation?
        let run_function = match function.test_filter(current) {
            Ok(r) => r,
            Err(e) => {
                results.push(TransformResult {
                    function_id: function.id,
                    outcome: TransformOutcome::FilterFailure(e),
                    logs: Vec::new(),
                });
                continue;
            }
        };

        if !run_function {
            results.push(TransformResult {
                function_id: function.id,
                outcome: TransformOutcome::Skipped,
                logs: Vec::new(),
            });
            continue;
        }

        // Apply it, storing the outcome into our final_event if it succeeds
        let result = match function.apply_transform(current) {
            Ok((new, logs)) => {
                final_event = new;
                TransformResult {
                    function_id: function.id,
                    outcome: TransformOutcome::Success,
                    logs,
                }
            }
            Err((e, logs)) => TransformResult {
                function_id: function.id,
                outcome: TransformOutcome::TransformFailure(e),
                logs,
            },
        };

        results.push(result);
    }

    TransformSetOutcome {
        results,
        final_event,
    }
}

impl ExecutableHogFunction {
    pub fn test_filter(&mut self, event: &ClickHouseEvent) -> Result<bool, VmError> {
        todo!()
    }

    pub fn apply_transform(
        &mut self,
        event: &ClickHouseEvent,
    ) -> Result<(Option<ClickHouseEvent>, Vec<TransformLog>), (VmError, Vec<TransformLog>)> {
        todo!()
    }
}
