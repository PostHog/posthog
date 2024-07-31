use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use serde_repr::{Deserialize_repr, Serialize_repr};
use sqlx::{Executor, Postgres};
use chrono::{DateTime, Utc};
use uuid::Uuid;

use crate::{app_context::AppContext, property_cache::{CacheError, SKIP_PROPERTIES}};


#[derive(Clone, Copy, Debug, Hash, Eq, PartialEq, Serialize, Deserialize)]
pub struct TeamId(pub i32);

#[derive(Clone, Debug, Hash, Eq, PartialEq)]
pub struct TeamEventId {
    pub team_id: TeamId,
    pub event_name: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize_repr, Deserialize_repr)]
#[repr(i16)]
pub enum PropertyParentType {
    Event = 1,
    Person = 2,
    Group = 3,
    Session = 4
}

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub enum PropertyValueType {
    DateTime,
    String,
    Numeric,
    Boolean,
    Duration
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
    pub group_type_index: Option<i16>,
    pub property_type_format: Option<String>, // This is deprecated, so don't bother validating it through serde
    pub volume_30_day: Option<i64>, // Deprecated
    pub query_usage_30_day: Option<i64>, // Deprecated
}

#[derive(Clone, Debug, Serialize, Eq, PartialEq)]
pub struct EventDefinition {
    pub id: Uuid,
    pub name: String,
    pub team_id: TeamId,
    #[serde(
        skip_serializing_if = "Option::is_none"
    )]
    pub last_seen_at: Option<DateTime<Utc>>, // Defaults to RFC 3339
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EventProperty(pub String);


#[derive(Clone, Debug, Deserialize)]
pub struct Event {
    pub team_id: TeamId,
    pub event: String,
    pub properties: Option<serde_json::Value>
}

impl From<&Event> for EventDefinition {
    fn from(event: &Event) -> Self {
        EventDefinition {
            id: Uuid::now_v7(),
            name: sanitize_event_name(&event.event),
            team_id: event.team_id,
            last_seen_at: None
        }
    }
}

impl Event {
    pub async fn get_properties(&self, context: &AppContext) -> Result<Vec<PropertyDefinition>, sqlx::Error> {
        let Some(props) = &self.properties else {
            return Ok(vec![]);
        };

        let Value::Object(props) = props else {
            return Ok(vec![]);
        };

        if self.event == "$groupidentify" {
            let Some(Value::String(group_type)) = props.get("$group_type") else {
                return Ok(vec![]);
            };
            let group_type_index = context.group_type_cache.get_group_type_index(self.team_id, group_type).await?;

            let Some(group_properties) = props.get("$group_set") else {
                return Ok(vec![]);
            };

            let Value::Object(group_properties) = group_properties else {
                return vec![];
            };
            return self.get_props_from_object(group_properties, PropertyParentType::Group, group_type_index)
        }

        let mut flat_props = self.get_props_from_object(props, PropertyParentType::Event, None);

        if let Some(Value::Object(set_props)) = props.get("$set") {
            flat_props.extend(self.get_props_from_object(set_props, PropertyParentType::Person, None));
        }
        if let Some(Value::Object(set_once_props)) = props.get("$set_once") {
            flat_props.extend(self.get_props_from_object(set_once_props, PropertyParentType::Person, None));
        }

        flat_props
    }

    fn get_props_from_object(&self, set: &Map<String, Value>, parent_type: PropertyParentType, group_type_index: Option<i16>) -> Vec<PropertyDefinition> {
        let mut to_return = vec![];
        for (key, value) in set{
            if SKIP_PROPERTIES.contains(&key.as_str()) && parent_type == PropertyParentType::Event {
                continue;
            }

            let is_numerical = value.is_number();
            let property_type = if is_numerical {
                Some(PropertyValueType::Numeric)
            } else {
                Some(PropertyValueType::String)
            };

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
                query_usage_30_day: None
            });
        }
        to_return
    }
}

fn sanitize_event_name(event_name: &str) -> String {
    event_name.replace("\u{0000}", "\u{FFFD}")
}

impl EventDefinition {

    pub fn set_last_seen(&mut self) {
        self.last_seen_at = Some(Utc::now());
    }

    pub async fn upsert<'c>(&self, db: impl Executor<'c, Database = Postgres>) -> Result<(), CacheError> {
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
            .map(|_| ())
    }
}

async fn get_group_type_index(group_type: &Value) -> i16 {
    todo!()
}