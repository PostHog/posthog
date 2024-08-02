use std::{fmt, str::FromStr};

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use serde_repr::{Deserialize_repr, Serialize_repr};
use sqlx::{Executor, Postgres};
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    property_cache::{CacheError, SKIP_PROPERTIES},
};

#[derive(Clone, Copy, Debug, Hash, Eq, PartialEq, Serialize, Deserialize)]
pub struct TeamId(pub i32);

#[derive(Clone, Debug, Hash, Eq, PartialEq)]
pub struct TeamEventId {
    pub team_id: TeamId,
    pub event_name: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize_repr, Deserialize_repr, Hash)]
#[repr(i16)]
pub enum PropertyParentType {
    Event = 1,
    Person = 2,
    Group = 3,
    Session = 4,
}

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub enum PropertyValueType {
    DateTime,
    String,
    Numeric,
    Boolean,
    Duration,
}

impl fmt::Display for PropertyValueType {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            PropertyValueType::DateTime => write!(f, "DateTime"),
            PropertyValueType::String => write!(f, "String"),
            PropertyValueType::Numeric => write!(f, "Numeric"),
            PropertyValueType::Boolean => write!(f, "Boolean"),
            PropertyValueType::Duration => write!(f, "Duration"),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub struct PropertyDefinition {
    pub id: Uuid,
    pub team_id: TeamId,
    pub name: String,
    pub is_numerical: bool,
    pub property_type: Option<PropertyValueType>,
    #[serde(rename = "type")]
    pub event_type: Option<PropertyParentType>,
    pub group_type_index: Option<i32>, // This is an i16 in the DB, but the groups table uses i16's, so we use that here and only downconvert on insert/read
    pub property_type_format: Option<String>, // This is deprecated, so don't bother validating it through serde
    pub volume_30_day: Option<i64>,           // Deprecated
    pub query_usage_30_day: Option<i64>,      // Deprecated
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct EventDefinition {
    pub id: Uuid,
    pub name: String,
    pub team_id: TeamId,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_seen_at: Option<DateTime<Utc>>, // Defaults to RFC 3339
}

#[derive(Clone, Debug, Deserialize)]
pub struct Event {
    pub team_id: TeamId,
    pub event: String,
    // Events in clickhouse_json have their properties as a raw string, so we have to parse it.
    pub properties: Option<String>,
}

impl From<&Event> for EventDefinition {
    fn from(event: &Event) -> Self {
        EventDefinition {
            id: Uuid::now_v7(),
            name: sanitize_event_name(&event.event),
            team_id: event.team_id,
            last_seen_at: None,
        }
    }
}

impl Event {
    pub async fn get_properties(
        &self,
        context: &AppContext,
    ) -> Result<Vec<PropertyDefinition>, sqlx::Error> {
        let Some(props) = &self.properties else {
            return Ok(vec![]);
        };

        let Ok(props) = Value::from_str(props) else {
            return Ok(vec![]);
        };

        let Value::Object(props) = props else {
            return Ok(vec![]);
        };

        if self.event == "$groupidentify" {
            let Some(Value::String(group_type)) = props.get("$group_type") else {
                return Ok(vec![]);
            };
            let group_type_index = context
                .group_type_cache
                .get_group_type_index(self.team_id, group_type)
                .await?;

            let Some(group_properties) = props.get("$group_set") else {
                return Ok(vec![]);
            };

            let Value::Object(group_properties) = group_properties else {
                return Ok(vec![]);
            };
            return Ok(self.get_props_from_object(
                group_properties,
                PropertyParentType::Group,
                group_type_index,
            ));
        }

        let mut flat_props = self.get_props_from_object(&props, PropertyParentType::Event, None);

        if let Some(Value::Object(set_props)) = props.get("$set") {
            flat_props.extend(self.get_props_from_object(
                set_props,
                PropertyParentType::Person,
                None,
            ));
        }
        if let Some(Value::Object(set_once_props)) = props.get("$set_once") {
            flat_props.extend(self.get_props_from_object(
                set_once_props,
                PropertyParentType::Person,
                None,
            ));
        }

        Ok(flat_props)
    }

    fn get_props_from_object(
        &self,
        set: &Map<String, Value>,
        parent_type: PropertyParentType,
        group_type_index: Option<i32>,
    ) -> Vec<PropertyDefinition> {
        let mut to_return = vec![];
        for (key, value) in set {
            if SKIP_PROPERTIES.contains(&key.as_str()) && parent_type == PropertyParentType::Event {
                continue;
            }

            let property_type = detect_property_type(key, value);
            let is_numerical = matches!(property_type, Some(PropertyValueType::Numeric));

            to_return.push(PropertyDefinition {
                id: Uuid::now_v7(),
                team_id: self.team_id,
                name: key.clone(),
                is_numerical,
                property_type,
                event_type: Some(parent_type),
                group_type_index,
                property_type_format: None,
                volume_30_day: None,
                query_usage_30_day: None,
            });
        }
        to_return
    }
}

fn detect_property_type(key: &str, value: &Value) -> Option<PropertyValueType> {
    // There are a whole set of special cases here, taken from the TS
    if key.starts_with("utm_") {
        // utm_ prefixed properties should always be detected as strings.
        // Sometimes the first value sent looks like a number, event though
        // subsequent values are not. See
        // https://github.com/PostHog/posthog/issues/12529 for more context.
        return Some(PropertyValueType::String);
    }
    if key.starts_with("$feature/") {
        // $feature/ prefixed properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return Some(PropertyValueType::String);
    }

    if key == "$feature_flag_response" {
        // $feature_flag_response properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return Some(PropertyValueType::String);
    }

    if key.starts_with("$survey_response") {
        // NB: $survey_responses are collected in an interesting way, where the first
        // response is called `$survey_response` and subsequent responses are called
        // `$survey_response_2`, `$survey_response_3`, etc.  So, this check should auto-cast
        // all survey responses to strings, and $survey_response properties should always be detected as strings.
        return Some(PropertyValueType::String);
    }

    match value {
        Value::String(s) => {
            let s = &s.trim().to_lowercase();
            if s == "true" || s == "false" {
                Some(PropertyValueType::Boolean)
            } else {
                // TODO - we should try to auto-detect datetime strings here, but I'm skipping the chunk of regex necessary to do it for v0
                Some(PropertyValueType::String)
            }
        }
        Value::Number(_) => {
            // TODO - this is a divergence from the TS impl - the TS also checks if the contained number is
            // "likely" to be a unix timestamp on the basis of the number of characters. I have mixed feelings about this,
            // so I'm going to leave it as just checking the key for now. This means we're being /less/ strict with datetime
            // detection here than in the TS
            if key.to_lowercase().contains("timestamp") || key.to_lowercase().contains("time") {
                Some(PropertyValueType::DateTime)
            } else {
                Some(PropertyValueType::Numeric)
            }
        }
        Value::Bool(_) => Some(PropertyValueType::Boolean),
        _ => None,
    }
}

fn sanitize_event_name(event_name: &str) -> String {
    event_name.replace('\u{0000}', "\u{FFFD}")
}

impl EventDefinition {
    pub fn set_last_seen(&mut self) {
        self.last_seen_at = Some(Utc::now());
    }

    pub async fn upsert<'c>(
        &self,
        db: impl Executor<'c, Database = Postgres>,
    ) -> Result<(), CacheError> {
        sqlx::query!(
            r#"
            INSERT INTO posthog_eventdefinition (id, name, team_id, volume_30_day, query_usage_30_day, created_at, last_seen_at)
            VALUES ($1, $2, $3, NULL, NULL, NOW(), $4)
            ON CONFLICT ON CONSTRAINT posthog_eventdefinition_team_id_name_80fa0b87_uniq DO UPDATE
            set last_seen_at = $4
            "#,
            self.id,
            self.name,
            self.team_id.0,
            self.last_seen_at
        )
            .execute(db)
            .await
            .map_err(CacheError::from)
            .map(|_| ())?;

        Ok(())
    }
}

impl PropertyDefinition {
    pub async fn upsert<'c>(
        &self,
        db: impl Executor<'c, Database = Postgres>,
    ) -> Result<(), CacheError> {
        let event_type = self.event_type.map(|e| (e as isize) as i16);

        let group_type_index = self.group_type_index.map(|i| {
            i as i16 // This is willfully unsafe because I'm a bad boy who likes to live dangerously
        });

        let property_type = self.property_type.as_ref().map(|p| p.to_string());

        sqlx::query!(
            r#"
            INSERT INTO posthog_propertydefinition (id, name, is_numerical, query_usage_30_day, property_type, property_type_format, volume_30_day, team_id, group_type_index, type)
            VALUES ($1, $2, $3, NULL, $4, NULL, NULL, $5, $6, $7)
            ON CONFLICT (team_id, name, type, coalesce(group_type_index, -1))
            DO UPDATE SET property_type = EXCLUDED.property_type WHERE posthog_propertydefinition.property_type IS NULL
            "#,
            self.id,
            self.name,
            self.is_numerical,
            property_type,
            self.team_id.0,
            group_type_index,
            event_type,
        )
            .execute(db)
            .await
            .map_err(CacheError::from)
            .map(|_| ())
    }
}
