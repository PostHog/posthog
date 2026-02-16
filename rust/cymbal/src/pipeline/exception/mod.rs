use std::sync::Arc;

use common_types::ClickHouseEvent;

use serde_json::Value;

pub mod issue_processing;
pub mod spike_detection;
pub mod stack_processing;

use crate::{
    app_context::AppContext,
    error::{EventError, PipelineFailure, PipelineResult, UnhandledError},
    recursively_sanitize_properties,
    stages::{consumer_pipeline::ConsumerEventPipeline, pipeline::ExceptionEventPipeline},
    types::{batch::Batch, event::AnyEvent, stage::Stage, RawErrProps},
};

pub const MAX_EXCEPTION_VALUE_LENGTH: usize = 10_000;

pub async fn do_exception_handling(
    events: Vec<PipelineResult>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let pipeline = ConsumerEventPipeline::new(context);
    let input_batch_events: Batch<Result<ClickHouseEvent, EventError>> = Batch::from(events);
    let output_batch_events = pipeline.process(input_batch_events).await?;
    output_batch_events
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

impl From<Batch<PipelineResult>> for Batch<Result<AnyEvent, EventError>> {
    fn from(value: Batch<PipelineResult>) -> Self {
        Batch::from(
            value
                .into_iter()
                .map(|item| match item {
                    Ok(evt) => AnyEvent::try_from(evt),
                    Err(err) => Err(err),
                })
                .collect::<Vec<_>>(),
        )
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use uuid::Uuid;

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
            captured_at: None,
            historical_migration: None,
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
