use std::collections::HashMap;

use common_types::{ClickHouseEvent, PersonMode};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    types::exception_properties::ExceptionProperties,
};

#[derive(Serialize, Deserialize, Clone)]
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

        // Serialize remaining ClickHouseEvent fields to `others` for round-trip preservation
        let mut others = HashMap::new();
        others.insert(
            "project_id".to_string(),
            serde_json::to_value(value.project_id).unwrap_or(Value::Null),
        );
        others.insert(
            "distinct_id".to_string(),
            Value::String(value.distinct_id.clone()),
        );
        others.insert(
            "person_id".to_string(),
            serde_json::to_value(&value.person_id).unwrap_or(Value::Null),
        );
        others.insert(
            "created_at".to_string(),
            Value::String(value.created_at.clone()),
        );
        if let Some(ref v) = value.captured_at {
            others.insert("captured_at".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.elements_chain {
            others.insert("elements_chain".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.person_created_at {
            others.insert("person_created_at".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.person_properties {
            others.insert("person_properties".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group0_properties {
            others.insert("group0_properties".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group1_properties {
            others.insert("group1_properties".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group2_properties {
            others.insert("group2_properties".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group3_properties {
            others.insert("group3_properties".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group4_properties {
            others.insert("group4_properties".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group0_created_at {
            others.insert("group0_created_at".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group1_created_at {
            others.insert("group1_created_at".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group2_created_at {
            others.insert("group2_created_at".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group3_created_at {
            others.insert("group3_created_at".to_string(), Value::String(v.clone()));
        }
        if let Some(ref v) = value.group4_created_at {
            others.insert("group4_created_at".to_string(), Value::String(v.clone()));
        }
        others.insert(
            "person_mode".to_string(),
            serde_json::to_value(value.person_mode).unwrap_or(Value::Null),
        );
        if let Some(ref v) = value.historical_migration {
            others.insert(
                "historical_migration".to_string(),
                serde_json::to_value(v).unwrap_or(Value::Null),
            );
        }

        Ok(AnyEvent {
            uuid: value.uuid,
            event: value.event,
            team_id: value.team_id,
            timestamp: value.timestamp,
            properties,
            others,
        })
    }
}

impl TryFrom<AnyEvent> for ClickHouseEvent {
    type Error = UnhandledError;
    fn try_from(value: AnyEvent) -> Result<Self, Self::Error> {
        let properties = serde_json::to_string(&value.properties)?;
        let others = value.others;

        fn get_string(others: &HashMap<String, Value>, key: &str) -> Option<String> {
            others.get(key).and_then(|v| v.as_str()).map(String::from)
        }

        fn get_optional_string(others: &HashMap<String, Value>, key: &str) -> Option<String> {
            match others.get(key) {
                Some(Value::String(s)) => Some(s.clone()),
                Some(Value::Null) | None => None,
                _ => None,
            }
        }

        let distinct_id = get_string(&others, "distinct_id")
            .ok_or_else(|| UnhandledError::Other("Missing distinct_id".into()))?;

        let created_at = get_string(&others, "created_at")
            .ok_or_else(|| UnhandledError::Other("Missing created_at".into()))?;

        let project_id = others.get("project_id").and_then(|v| match v {
            Value::Number(n) => n.as_i64(),
            Value::Null => None,
            _ => None,
        });

        let person_mode: PersonMode = others
            .get("person_mode")
            .map(|v| serde_json::from_value(v.clone()))
            .transpose()?
            .unwrap_or(PersonMode::Full);

        let historical_migration = others.get("historical_migration").and_then(|v| v.as_bool());

        Ok(ClickHouseEvent {
            uuid: value.uuid,
            team_id: value.team_id,
            project_id,
            event: value.event,
            distinct_id,
            properties: Some(properties),
            person_id: get_optional_string(&others, "person_id"),
            timestamp: value.timestamp,
            created_at,
            captured_at: get_optional_string(&others, "captured_at"),
            elements_chain: get_optional_string(&others, "elements_chain"),
            person_created_at: get_optional_string(&others, "person_created_at"),
            person_properties: get_optional_string(&others, "person_properties"),
            group0_properties: get_optional_string(&others, "group0_properties"),
            group1_properties: get_optional_string(&others, "group1_properties"),
            group2_properties: get_optional_string(&others, "group2_properties"),
            group3_properties: get_optional_string(&others, "group3_properties"),
            group4_properties: get_optional_string(&others, "group4_properties"),
            group0_created_at: get_optional_string(&others, "group0_created_at"),
            group1_created_at: get_optional_string(&others, "group1_created_at"),
            group2_created_at: get_optional_string(&others, "group2_created_at"),
            group3_created_at: get_optional_string(&others, "group3_created_at"),
            group4_created_at: get_optional_string(&others, "group4_created_at"),
            person_mode,
            historical_migration,
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
}
