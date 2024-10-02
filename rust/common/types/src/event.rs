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
