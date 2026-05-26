//! Ordering and result-merging utilities shared by the batch and streaming
//! orchestrators.
//!
//! This module owns the pure helpers that:
//!
//! * split per-stage outputs into "continue" and terminal `EventResult` halves
//!   so the orchestrator can merge terminal results back into the final
//!   ordered output,
//! * reorder a flat result vector to match the original input order, and
//! * convert linking outcomes into alerting inputs.
//!
//! Concerns that explicitly do not belong here: stage execution, streaming
//! sinks, or transport. Those live in [`crate::executor`], [`crate::streaming`],
//! and [`crate::sink`].

use std::collections::HashMap;

use cymbal_alerting::AlertingEvent;
use cymbal_core::StageError;
use cymbal_domain::{EventResult, InputEvent, RateLimitGateOutput};

use crate::IntermediateStageOutput;

pub fn split_rate_limit_outputs(
    outputs: Vec<RateLimitGateOutput>,
) -> (Vec<InputEvent>, Vec<EventResult>) {
    let mut allowed_events = Vec::new();
    let mut terminal_results = Vec::new();

    for output in outputs {
        match output {
            RateLimitGateOutput::Allowed(allowed) => allowed_events.push(allowed.event),
            RateLimitGateOutput::Terminal(result) => terminal_results.push(result),
        }
    }

    (allowed_events, terminal_results)
}

pub fn split_intermediate_outputs<T>(
    outputs: Vec<IntermediateStageOutput<T>>,
) -> (Vec<T>, Vec<EventResult>) {
    let mut next_items = Vec::new();
    let mut terminal_results = Vec::new();

    for output in outputs {
        match output {
            IntermediateStageOutput::Continue(item) => next_items.push(item),
            IntermediateStageOutput::Terminal(result) => terminal_results.push(result),
        }
    }

    (next_items, terminal_results)
}

pub fn order_event_results(
    input_event_ids: Vec<String>,
    results: Vec<EventResult>,
) -> Result<Vec<EventResult>, StageError> {
    let mut results_by_event_id = HashMap::with_capacity(results.len());
    for result in results {
        let previous = results_by_event_id.insert(result.event_id.clone(), result);
        if previous.is_some() {
            return Err(StageError::Internal(
                "pipeline produced duplicate results for an event".to_string(),
            ));
        }
    }

    let mut ordered_results = Vec::with_capacity(input_event_ids.len());
    for event_id in input_event_ids {
        let Some(result) = results_by_event_id.remove(&event_id) else {
            return Err(StageError::Internal(format!(
                "pipeline produced no result for event {event_id}"
            )));
        };
        ordered_results.push(result);
    }
    if !results_by_event_id.is_empty() {
        return Err(StageError::Internal(
            "pipeline produced results for events that were not in the input".to_string(),
        ));
    }

    Ok(ordered_results)
}

pub(crate) fn sort_by_input_order<T>(
    mut items: Vec<T>,
    input_index_by_event_id: &HashMap<String, usize>,
    event_id: impl Fn(&T) -> &str,
) -> Vec<T> {
    items.sort_by_key(|item| {
        input_index_by_event_id
            .get(event_id(item))
            .copied()
            .unwrap_or(usize::MAX)
    });
    items
}

pub fn event_result_to_alerting_event(result: EventResult) -> AlertingEvent {
    AlertingEvent {
        result,
        spike_alert_input: None,
    }
}
