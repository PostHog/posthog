use serde::{Deserialize, Serialize};
use time::OffsetDateTime;
use uuid::Uuid;

// The event type that capture produces
#[derive(Clone, Debug, Serialize, Deserialize, Eq, PartialEq)]
pub struct CapturedEvent {
    pub uuid: Uuid,
    pub distinct_id: String,
    pub ip: String,
    pub data: String,
    pub now: String,
    #[serde(
        with = "time::serde::rfc3339::option",
        skip_serializing_if = "Option::is_none"
    )]
    pub sent_at: Option<OffsetDateTime>,
    pub token: String,
}

impl CapturedEvent {
    pub fn key(&self) -> String {
        format!("{}:{}", self.token, self.distinct_id)
    }
}

#[derive(Debug, Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "snake_case")]
pub enum PersonMode {
    Full,
    Propertyless,
    ForceUpgrade,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ClickHouseEvent {
    pub uuid: Uuid,
    pub team_id: i32,
    pub event: String,
    pub distinct_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub person_id: Option<String>,
    // TODO: verify timestamp format
    pub timestamp: String,
    // TODO: verify timestamp format
    pub created_at: String,
    pub elements_chain: String,
    // TODO: verify timestamp format
    #[serde(skip_serializing_if = "Option::is_none")]
    pub person_created_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub person_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group0_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group1_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group2_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group3_properties: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group4_properties: Option<String>,
    // TODO: verify timestamp format
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group0_created_at: Option<String>,
    // TODO: verify timestamp format
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group1_created_at: Option<String>,
    // TODO: verify timestamp format
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group2_created_at: Option<String>,
    // TODO: verify timestamp format
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group3_created_at: Option<String>,
    // TODO: verify timestamp format
    #[serde(skip_serializing_if = "Option::is_none")]
    pub group4_created_at: Option<String>,
    pub person_mode: PersonMode,
}
