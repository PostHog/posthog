//! The wire contract for the `error-tracking-ingestion-notifications` Kafka
//! topic. The processing mode produces these; the notifications mode consumes
//! them. Lives in `core` so both modes share one definition.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

/// A notification emitted by error-tracking ingestion. Serialized as
/// internally-tagged JSON (`{"type": "issue_created", ...}`) so new variants can
/// be added without breaking existing consumers — an unknown `type` simply fails
/// to deserialize and is skipped as a poison pill.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum IngestionNotification {
    /// A new issue was created during ingestion.
    IssueCreated(IssueCreated),
}

/// Payload for [`IngestionNotification::IssueCreated`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IssueCreated {
    pub team_id: i32,
    pub issue_id: Uuid,
    pub name: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
    /// The symbolicated exception event that triggered issue creation, carried
    /// as raw JSON so `core` stays free of processing-only types. The producer
    /// serializes its output exception properties here.
    pub event: Value,
    /// Timestamp of the originating exception event (distinct from the issue's
    /// `created_at`).
    pub event_timestamp: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn issue_created_round_trips_with_type_tag() {
        let notification = IngestionNotification::IssueCreated(IssueCreated {
            team_id: 42,
            issue_id: Uuid::nil(),
            name: Some("TypeError".to_string()),
            description: None,
            created_at: DateTime::from_timestamp(0, 0).unwrap(),
            event: serde_json::json!({"$exception_fingerprint": "abc"}),
            event_timestamp: DateTime::from_timestamp(0, 0).unwrap(),
        });

        let json = serde_json::to_value(&notification).unwrap();
        assert_eq!(json["type"], "issue_created");
        assert_eq!(json["team_id"], 42);
        assert_eq!(json["event"]["$exception_fingerprint"], "abc");

        let decoded: IngestionNotification = serde_json::from_value(json).unwrap();
        assert_eq!(decoded, notification);
    }
}
