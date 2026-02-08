use std::sync::Arc;

use common_types::ClickHouseEvent;
use issue_processing::do_issue_processing;
use metrics::counter;
use serde_json::Value;
use stack_processing::do_stack_processing;
use tracing::{error, warn};
use uuid::Uuid;

pub mod issue_processing;
pub mod spike_detection;
pub mod stack_processing;

use crate::{
    app_context::AppContext,
    error::{EventError, PipelineFailure, PipelineResult, UnhandledError},
    issue_resolution::{Issue, IssueStatus},
    metric_consts::{
        ISSUE_PROCESSING_TIME, SPIKE_DETECTION_TIME, STACK_PROCESSING_TIME,
        SUPPRESSED_ISSUE_DROPPED_EVENTS,
    },
    recursively_sanitize_properties,
    types::RawErrProps,
};

const MAX_EXCEPTION_VALUE_LENGTH: usize = 10_000;

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
    let issues = do_issue_processing(context.clone(), &events, &fingerprinted).await?;
    issue_timer.fin();

    // Unfreeze, as we're about to replace the event properties.
    let mut events = events;
    let mut issue_counts: std::collections::HashMap<Uuid, u32> = std::collections::HashMap::new();
    let mut issues_by_id: std::collections::HashMap<Uuid, Issue> = std::collections::HashMap::new();
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
        event.properties =
            Some(serde_json::to_string(&output).map_err(|e| (index, Arc::new(e.into())))?);
        *issue_counts.entry(issue.id).or_insert(0) += 1;
        issues_by_id.entry(issue.id).or_insert(issue);
    }

    let spike_timer = common_metrics::timing_guard(SPIKE_DETECTION_TIME, &[]);
    spike_detection::do_spike_detection(context, issues_by_id, issue_counts).await;
    spike_timer.fin();

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

    let mut props: RawErrProps = match serde_json::from_value(properties) {
        Ok(r) => r,
        Err(e) => {
            return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
        }
    };

    for exception in props.exception_list.iter_mut() {
        if exception.exception_message.len() > MAX_EXCEPTION_VALUE_LENGTH {
            let truncate_at = exception
                .exception_message
                .char_indices()
                .take_while(|(i, _)| *i < MAX_EXCEPTION_VALUE_LENGTH)
                .last()
                .map(|(i, c)| i + c.len_utf8())
                .unwrap_or(0);
            exception.exception_message.truncate(truncate_at);
            exception.exception_message.push_str("...");
        }
    }

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

#[cfg(test)]
mod test {
    use super::*;

    fn make_exception_event(exception_value: &str) -> ClickHouseEvent {
        let props = serde_json::json!({
            "$exception_list": [{
                "type": "Error",
                "value": exception_value
            }]
        });
        ClickHouseEvent {
            uuid: Uuid::now_v7(),
            team_id: 1,
            project_id: Some(1),
            event: "$exception".to_string(),
            distinct_id: "test".to_string(),
            properties: Some(props.to_string()),
            timestamp: "2021-01-01T00:00:00Z".to_string(),
            created_at: "2021-01-01T00:00:00Z".to_string(),
            elements_chain: None,
            person_id: None,
            person_created_at: None,
            person_properties: None,
            group0_properties: None,
            group1_properties: None,
            group2_properties: None,
            group3_properties: None,
            group4_properties: None,
            group0_created_at: None,
            group1_created_at: None,
            group2_created_at: None,
            group3_created_at: None,
            group4_created_at: None,
            person_mode: common_types::PersonMode::Full,
        }
    }

    #[test]
    fn test_exception_value_truncation() {
        let long_value = "x".repeat(MAX_EXCEPTION_VALUE_LENGTH + 100);
        let event = make_exception_event(&long_value);
        let props = get_props(&event).unwrap();

        let expected = format!("{}...", "x".repeat(MAX_EXCEPTION_VALUE_LENGTH));
        assert_eq!(props.exception_list[0].exception_message, expected);
    }
}
