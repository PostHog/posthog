use std::sync::Arc;

use common_types::ClickHouseEvent;
use issue_processing::do_issue_processing;
use metrics::counter;
use serde_json::Value;
use stack_processing::do_stack_processing;
use tracing::{error, warn};

pub mod issue_processing;
pub mod stack_processing;

use crate::{
    app_context::AppContext,
    error::{EventError, PipelineFailure, PipelineResult, UnhandledError},
    issue_resolution::IssueStatus,
    metric_consts::{
        ISSUE_PROCESSING_TIME, STACK_PROCESSING_TIME, SUPPRESSED_ISSUE_DROPPED_EVENTS,
    },
    recursively_sanitize_properties,
    types::RawErrProps,
};

pub async fn do_exception_handling(
    mut events: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    // First pass through the event list, to get all the exception property sets
    // we'll process. Events we don't get exception properties from will be skipped
    // in all the following passes
    let mut indexed_props = Vec::new();
    for (index, event) in events.iter_mut().enumerate() {
        let Ok(event) = event else {
            continue; // some earlier stage already caused this event to be dropped, so we don't need to process it further.
        };
        match get_props(event) {
            Ok(r) => indexed_props.push((index, r)),
            Err(e) => {
                warn!(team = event.team_id, "Failed to get props: {}", e);
                if let Err(e) = add_error_to_event(event, e) {
                    // If we fail to add an error to an event, we just log it.
                    // This can happen if we failed to read the properties
                    // of the event at all, e.g. due to a serde recursion limit.
                    error!(team = event.team_id, "Failed to add error to event: {}", e);
                }
                continue;
            }
        };
    }

    // Freeze the events list as immutable until the final stage, to ensure we don't
    // accidentally mutate or drop an event during processing - this ensures tha validity
    // of the indexes in indexed_props.
    let events = events;

    let stack_timer = common_metrics::timing_guard(STACK_PROCESSING_TIME, &[]);
    let fingerprinted = do_stack_processing(context.clone(), &events, indexed_props).await?;
    stack_timer.fin();

    let issue_timer = common_metrics::timing_guard(ISSUE_PROCESSING_TIME, &[]);
    let issues = do_issue_processing(context, &events, &fingerprinted).await?;
    issue_timer.fin();

    // Unfreeze, as we're about to replace the event properties.
    let mut events = events;
    for (index, fingerprinted) in fingerprinted.into_iter() {
        let issue = issues
            .get(&fingerprinted.fingerprint.value)
            .cloned()
            .expect("Issue was resolved");

        if matches!(issue.status, IssueStatus::Suppressed) {
            counter!(SUPPRESSED_ISSUE_DROPPED_EVENTS).increment(1);
            events[index] = Err(EventError::Suppressed(issue.id));
            continue;
        }

        let Ok(event) = &mut events[index] else {
            panic!("Event list modified since indexed property gathering");
        };

        let output = fingerprinted.to_output(issue.id);
        event.properties = Some(serde_json::to_string(&output).map_err(|e| (index, e.into()))?);
    }

    Ok(events)
}

pub fn get_props(event: &ClickHouseEvent) -> Result<RawErrProps, EventError> {
    if event.event != "$exception" {
        return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
    }

    let Some(properties) = &event.properties else {
        return Err(EventError::NoProperties(event.uuid));
    };

    let mut properties: Value = match serde_json::from_str(properties) {
        Ok(r) => r,
        Err(e) => {
            return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
        }
    };

    if let Some(v) = properties
        .as_object_mut()
        .and_then(|o| o.get_mut("$exception_list"))
    {
        // We PG sanitize the exception list, because the strings in it can end up in PG kind of arbitrarily.
        // TODO - the prep stage has already sanitized the properties, so maybe we don't need to do this again?
        recursively_sanitize_properties(event.uuid, v, 0)?;
    }

    let props: RawErrProps = match serde_json::from_value(properties) {
        Ok(r) => r,
        Err(e) => {
            return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
        }
    };

    if props.exception_list.is_empty() {
        return Err(EventError::EmptyExceptionList(event.uuid));
    }

    Ok(props)
}

// This is expensive, since it round-trips the event through JSON.
// We could maybe change ClickhouseEvent to only do serde at the edges
pub fn add_error_to_event(
    event: &mut ClickHouseEvent,
    e: impl ToString,
) -> Result<(), UnhandledError> {
    let mut props = event.take_raw_properties()?;
    let mut errors = match props.remove("$cymbal_errors") {
        Some(serde_json::Value::Array(errors)) => errors,
        _ => Vec::new(),
    };

    errors.push(serde_json::Value::String(e.to_string()));
    props.insert(
        "$cymbal_errors".to_string(),
        serde_json::Value::Array(errors),
    );
    event.set_raw_properties(props)?;
    Ok(())
}
