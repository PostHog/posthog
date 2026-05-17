use std::collections::HashMap;

use common_types::ClickHouseEvent;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    types::exception_properties::ExceptionProperties,
};

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct AnyEvent {
    pub uuid: Uuid,
    pub event: String,
    pub team_id: i32,
    pub timestamp: String,

    pub properties: Value,

    #[serde(flatten)]
    pub others: HashMap<String, Value>,
}

pub trait PropertiesContainer: Send + Clone + 'static {
    fn set_properties(&mut self, new_props: ExceptionProperties) -> Result<(), UnhandledError>;
    fn attach_error(&mut self, error: String) -> Result<(), UnhandledError>;
}

impl PropertiesContainer for AnyEvent {
    fn set_properties(&mut self, new_props: ExceptionProperties) -> Result<(), UnhandledError> {
        self.properties = serde_json::to_value(&new_props)?;
        Ok(())
    }

    fn attach_error(&mut self, error: String) -> Result<(), UnhandledError> {
        let mut props: HashMap<String, Value> = serde_json::from_value(self.properties.take())?;
        let mut errors = match props.remove("$cymbal_errors") {
            Some(serde_json::Value::Array(errors)) => errors,
            _ => Vec::new(),
        };
        errors.push(serde_json::Value::String(error));
        props.insert(
            "$cymbal_errors".to_string(),
            serde_json::Value::Array(errors),
        );
        self.properties = serde_json::to_value(props)?;
        Ok(())
    }
}

impl TryFrom<ClickHouseEvent> for AnyEvent {
    type Error = EventError;
    fn try_from(value: ClickHouseEvent) -> Result<Self, Self::Error> {
        let properties = match &value.properties {
            Some(p) => serde_json::from_str(p)
                .map_err(|e| EventError::InvalidProperties(value.uuid, e.to_string()))?,
            None => Value::Null,
        };

        Ok(AnyEvent {
            uuid: value.uuid,
            event: value.event,
            team_id: value.team_id,
            timestamp: value.timestamp,
            properties,
            // We don't preserve all properties from ClickhouseEvent
            others: HashMap::new(),
        })
    }
}

#[cfg(test)]
mod test {
    use crate::types::exception_properties::MAX_EXCEPTION_VALUE_LENGTH;

    use super::*;
    use uuid::Uuid;

    fn make_exception_event(exception_value: &str) -> ClickHouseEvent {
        let props = serde_json::json!({
            "$exception_list": [{
                "type": "Error",
                "value": exception_value
            }]
        });
        make_exception_event_with_props(props)
    }

    fn make_exception_event_with_props(props: serde_json::Value) -> ClickHouseEvent {
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
        let any_event = AnyEvent::try_from(event).unwrap();
        let exc_props = ExceptionProperties::try_from(any_event).unwrap();

        let expected = format!("{}...", "x".repeat(MAX_EXCEPTION_VALUE_LENGTH));
        assert_eq!(exc_props.exception_list[0].exception_message, expected);
    }

    #[test]
    fn test_legacy_exception_type_and_message_fallback() {
        // Older SDKs and custom integrations send $exception_type / $exception_message
        // instead of a structured $exception_list. Without the backward-compat shim,
        // these events are silently dropped from error tracking.
        let props = serde_json::json!({
            "$exception_type": "ReferenceError",
            "$exception_message": "x is not defined"
        });
        let event = make_exception_event_with_props(props);
        let any_event = AnyEvent::try_from(event).unwrap();
        let exc_props = ExceptionProperties::try_from(any_event).unwrap();

        assert_eq!(exc_props.exception_list.len(), 1);
        assert_eq!(exc_props.exception_list[0].exception_type, "ReferenceError");
        assert_eq!(
            exc_props.exception_list[0].exception_message,
            "x is not defined"
        );
    }

    #[test]
    fn test_legacy_exception_type_without_message() {
        // Only $exception_type is required to reconstruct a minimal list.
        let props = serde_json::json!({
            "$exception_type": "TypeError"
        });
        let event = make_exception_event_with_props(props);
        let any_event = AnyEvent::try_from(event).unwrap();
        let exc_props = ExceptionProperties::try_from(any_event).unwrap();

        assert_eq!(exc_props.exception_list.len(), 1);
        assert_eq!(exc_props.exception_list[0].exception_type, "TypeError");
        assert_eq!(exc_props.exception_list[0].exception_message, "");
    }

    #[test]
    fn test_truly_empty_exception_list_still_errors() {
        // When neither $exception_list nor $exception_type is present, fall through
        // to the original EmptyExceptionList error so the event is dead-lettered.
        let props = serde_json::json!({
            "some_other_prop": "value"
        });
        let event = make_exception_event_with_props(props);
        let any_event = AnyEvent::try_from(event).unwrap();
        let result = ExceptionProperties::try_from(any_event);
        assert!(matches!(result, Err(EventError::EmptyExceptionList(_))));
    }
}
