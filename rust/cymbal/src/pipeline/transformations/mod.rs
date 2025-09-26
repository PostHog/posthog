use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use chrono::Utc;
use common_types::{ClickHouseEvent, Team};
use hogvm::{
    ExecutionContext, HogLiteral, HogVM, HogValue, NativeFunction, Program, StepOutcome, VmError,
};
use metrics::counter;
use serde_json::Value;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{PipelineFailure, PipelineResult},
    metric_consts::TRANSFORMATION_EVENTS_DROPPED,
    pipeline::transformations::types::{
        transform_globals::{self, FilterGlobals, FunctionContext, InvocationGlobals},
        HogFunction, HogFunctionFilter, TransformLog, TransformOutcome, TransformResult,
        TransformSetOutcome,
    },
};

pub mod transform;
pub mod types;

// TODO - there's just ample room for optimization here, if anyone feels like picking it up. Ofc, take a look at the timing metrics first.

// We could, and probably should, cache these, rather than caching the raw HogFunction's
struct ExecutableHogFunction {
    function: HogFunction,
    context: FunctionContext,
    transform_program: Program,
    filter_program: Option<Program>,
}

pub async fn apply_transformations(
    events: Vec<PipelineResult>,
    context: Arc<AppContext>,
    teams_lut: &HashMap<i32, Team>, // Needed for constructing invocation globals
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    // First, convert the hog function list for each team into an execution context list for each team
    let mut executable_lists = HashMap::new();

    // TODO - this entire loop could instead by done one a per-team bases within the manager itself, and the outcome
    // vec cached, rather than caching the raw HogFunction's.
    for (i, team_id) in events
        .iter()
        .filter_map(|e| e.as_ref().ok())
        .map(|event| event.team_id)
        .enumerate()
    {
        if executable_lists.contains_key(&team_id) {
            continue;
        }

        let functions = context
            .team_manager
            .function_manager
            .get_functions(&context.pool, team_id)
            .await
            .map_err(|e| (i, e))?;

        let mut executables = Vec::new();

        // These are used to construct the globals for the invocation
        let team = teams_lut
            .get(&team_id)
            .expect("We have found the team for the event we're processing");
        let group_types = context
            .team_manager
            .get_group_types(&context.pool, team_id)
            .await
            .map_err(|e| (i, e))?;

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
            let inputs = context
                .team_manager
                .function_manager
                .get_function_inputs(&context.encrypted_secrets_keys, &function)
                .await
                .map_err(|e| (i, e))?;

            let function_context =
                FunctionContext::new(&context.config.site_url, &group_types, &team, inputs);

            let Some(filters) = &function.filters else {
                executables.push(ExecutableHogFunction {
                    function,
                    context: function_context,
                    transform_program,
                    filter_program: None,
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
                    function,
                    context: function_context,
                    transform_program,
                    filter_program: None,
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

            executables.push(ExecutableHogFunction {
                function,
                context: function_context,
                transform_program,
                filter_program: Some(filter_program),
            });
        }

        executable_lists.insert(team_id, executables);
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

        let Some(list) = executable_lists.get(&event.team_id) else {
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
    executable_list: &[ExecutableHogFunction],
) -> TransformSetOutcome {
    let mut results = Vec::new();

    let mut final_event = Some(event);

    for executable in executable_list.iter() {
        // If the last transform dropped the event, we can exit early.
        let Some(current) = final_event.as_ref() else {
            break;
        };

        // Should we apply this transformation?
        let run_function = match executable.test_filter(current) {
            Ok(r) => r,
            Err(e) => {
                results.push(TransformResult {
                    function_id: executable.function.id,
                    outcome: TransformOutcome::FilterFailure(e),
                    logs: Vec::new(),
                });
                continue;
            }
        };

        if !run_function {
            results.push(TransformResult {
                function_id: executable.function.id,
                outcome: TransformOutcome::Skipped,
                logs: Vec::new(),
            });
            continue;
        }

        // Apply it, storing the outcome into our final_event if it succeeds
        let result = match executable.apply_transform(current) {
            Ok((new, logs)) => {
                final_event = new;
                TransformResult {
                    function_id: executable.function.id,
                    outcome: TransformOutcome::Success,
                    logs,
                }
            }
            Err((e, logs)) => TransformResult {
                function_id: executable.function.id,
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
    pub fn test_filter(&self, event: &ClickHouseEvent) -> Result<bool, VmError> {
        let Some(program) = self.filter_program.as_ref().cloned() else {
            return Ok(true); // Transforms with no filter match all events
        };

        // Right now, transformation filters lack a final return. For assignment and grouping rules, we handle this
        // on the compilation side, by adding it to the AST before final compilation, but the CDP side expects the
        // return-less filter programs for transforms, so we can't do that there. Instead, we just append a return
        // statement to the program here.
        let mut program = program;
        program.bytecode.push(hogvm::Operation::Return.into());
        let program = program;

        let globals = FilterGlobals::new(&self.context, event);

        let exec_context = ExecutionContext::with_defaults(program).with_globals(
            serde_json::to_value(globals)
                .expect("We successfully json serialise the filter globals"),
        );

        let mut vm = HogVM::new(&exec_context)?;
        let mut i = 0;
        while i < exec_context.max_steps {
            let step_result = vm.step()?;
            match step_result {
                StepOutcome::Finished(Value::Bool(b)) => return Ok(b),
                StepOutcome::Finished(other) => {
                    return Err(VmError::Other(format!(
                        "Transform filter returned {other:?}, expected a boolean value"
                    )))
                }
                StepOutcome::NativeCall(name, args) => {
                    exec_context.execute_native_function_call(&mut vm, &name, args)?
                }
                StepOutcome::Continue => {}
            }
            i += 1;
        }
        Err(VmError::OutOfResource("steps".to_string()))
    }

    pub fn apply_transform(
        &self,
        event: &ClickHouseEvent,
    ) -> Result<(Option<ClickHouseEvent>, Vec<TransformLog>), (VmError, Vec<TransformLog>)> {
        let program = self.transform_program.clone();
        let logs = Arc::new(Mutex::new(Vec::new()));

        let globals = InvocationGlobals::new(&self.context, event);
        let exec_context = ExecutionContext::with_defaults(program)
            .with_globals(
                serde_json::to_value(globals)
                    .expect("We successfully json serialise the filter globals"),
            )
            .with_ext_fn("print".to_string(), Self::make_print_function(logs.clone()));

        let mut vm = HogVM::new(&exec_context).map_err(|e| (e, (*logs.lock().unwrap()).clone()))?;
        let mut i = 0;
        while i < exec_context.max_steps {
            let step_result = vm
                .step()
                .map_err(|e| (e, (*logs.lock().unwrap()).clone()))?;
            match step_result {
                StepOutcome::Finished(return_val) => {
                    let logs = logs.lock().unwrap().clone();
                    match return_val {
                        Value::Null => return Ok((None, logs)),
                        Value::Object(map) => {
                            match serde_json::from_value::<transform_globals::Event>(Value::Object(
                                map,
                            )) {
                                Err(e) => {
                                    return Err((
                                        VmError::Other(format!("Failed to parse JSON: {}", e)),
                                        logs,
                                    ))
                                }
                                Ok(parsed) => {
                                    let updated = Self::apply_event_update(event, parsed)
                                        .map_err(|e| (e, logs.clone()))?;
                                    return Ok((Some(updated), logs));
                                }
                            }
                        }
                        Value::Bool(_) => {
                            return Err((
                                VmError::Other("Transform returned a bool".to_string()),
                                logs,
                            ))
                        }
                        Value::Number(_) => {
                            return Err((
                                VmError::Other("Transform returned a number".to_string()),
                                logs,
                            ))
                        }
                        Value::String(_) => {
                            return Err((
                                VmError::Other("Transform returned a string".to_string()),
                                logs,
                            ))
                        }
                        Value::Array(_) => {
                            return Err((
                                VmError::Other("Transform returned an array".to_string()),
                                logs,
                            ))
                        }
                    }
                }
                StepOutcome::NativeCall(name, args) => exec_context
                    .execute_native_function_call(&mut vm, &name, args)
                    .map_err(|e| (e, (*logs.lock().unwrap()).clone()))?,
                StepOutcome::Continue => {}
            }
            i += 1;
        }

        let logs = logs.lock().unwrap();
        let logs = logs.clone();
        Err((VmError::OutOfResource("steps".to_string()), logs))
    }

    fn make_print_function(logs: Arc<Mutex<Vec<TransformLog>>>) -> NativeFunction {
        Box::new(move |_vm: &HogVM, _args: Vec<HogValue>| {
            logs.lock().unwrap().push(TransformLog {
                message: "TODO".to_string(),
                level: "info".to_string(),
                timestamp: Utc::now(),
            });
            Ok(HogLiteral::Null.into())
        })
    }

    fn apply_event_update(
        event: &ClickHouseEvent,
        parsed: transform_globals::Event,
    ) -> Result<ClickHouseEvent, VmError> {
        // For now, we only allow transforms to modify properties
        let mut new_event = event.clone();
        new_event.properties = Some(serde_json::to_string(&parsed.properties).map_err(|e| {
            VmError::Other(format!(
                "Failed to serialise function output: {}",
                e.to_string()
            ))
        })?);

        Ok(new_event)
    }
}
