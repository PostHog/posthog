use serde::{Deserialize, Serialize};
use serde_repr::{Deserialize_repr, Serialize_repr};
use time::OffsetDateTime;
use uuid::Uuid;


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
    pub volume_30_day: Option<i64>, // Deprecated
    pub query_usage_30_day: Option<i64>, // Deprecated
    #[serde(
        with = "time::serde::rfc3339::option",
        skip_serializing_if = "Option::is_none"
    )]
    pub created_at: Option<OffsetDateTime>,
    #[serde(
        with = "time::serde::rfc3339::option",
        skip_serializing_if = "Option::is_none"
    )]
    pub last_seen_at: Option<OffsetDateTime>,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Event {
    pub team_id: i64,
    pub event: String,
    pub properties: Option<serde_json::Value>
}
