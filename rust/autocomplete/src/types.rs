use serde::{Deserialize, Serialize};
use serde_repr::{Deserialize_repr, Serialize_repr};
use sqlx::{Executor, Postgres};
use time::OffsetDateTime;
use uuid::Uuid;

use crate::cache::CacheError;


#[derive(Clone, Debug, Hash, Eq, PartialEq)]
pub struct TeamId(pub i64);

#[derive(Clone, Debug, Hash, Eq, PartialEq)]
pub struct TeamEventId {
    pub team_id: TeamId,
    pub event_name: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize_repr, Deserialize_repr)]
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
    pub team_id: i64,
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
    pub team_id: i64,
    #[serde(
        with = "time::serde::rfc3339::option",
        skip_serializing_if = "Option::is_none"
    )]
    pub last_seen_at: Option<OffsetDateTime>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EventProperty(pub String);


#[derive(Clone, Debug, Deserialize)]
pub struct Event {
    pub team_id: i64,
    pub event: String,
    pub properties: Option<serde_json::Value>
}

impl From<&Event> for EventDefinition {
    fn from(event: &Event) -> Self {
        EventDefinition {
            id: Uuid::now_v7(),
            name: event.event.clone(),
            team_id: event.team_id,
            last_seen_at: None
        }
    }
}

impl EventDefinition {

    pub fn set_last_seen(&mut self) {
        self.last_seen_at = Some(OffsetDateTime::now_utc());
    }

    pub async fn upsert<'c>(&self, db: impl Executor<'c, Database = Postgres>) -> Result<(), CacheError> {
        sqlx::query(
            r#"
            INSERT INTO posthog_eventdefinition (id, name, team_id, volume_30_day, query_usage_30_day, created_at, last_seen_at)
            VALUES ($1, $2, $3, NULL, NULL, NOW(), $4)
            ON CONFLICT ON CONSTRAINT posthog_eventdefinition_team_id_name_80fa0b87_uniq DO UPDATE
            set last_seen_at = $4
            "#
        )
            .bind(&self.id)
            .bind(&self.name)
            .bind(&self.team_id)
            .bind(&self.last_seen_at)
            .execute(db)
            .await
            .map_err(CacheError::from)
            .map(|_| ())
    }
}