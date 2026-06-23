//! The wire contract for the `error-tracking-ingestion-notifications` Kafka
//! topic. The processing mode produces these; the notifications mode consumes
//! them. Lives in `core` so both modes share one definition.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::core::types::Exception;

/// A notification emitted by error-tracking ingestion. Serialized as
/// internally-tagged JSON (`{"type": "issue_created", ...}`) so new variants can
/// be added without breaking existing consumers — an unknown `type` simply fails
/// to deserialize and is skipped as a poison pill.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum IngestionNotification {
    /// A new issue was created during ingestion.
    IssueCreated(IssueCreated),
}

/// Payload for [`IngestionNotification::IssueCreated`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueCreated {
    pub team_id: i32,
    pub issue_id: Uuid,
    pub name: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
    /// The exception event that triggered issue creation.
    pub event: IssueEvent,
    /// Timestamp of the originating exception event (distinct from the issue's
    /// `created_at`).
    pub event_timestamp: DateTime<Utc>,
}

/// The symbolicated exception event that triggered issue creation. Built from
/// shared `core` types — the producer projects its richer output properties
/// down to this, so `core` carries no processing-only dependency.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueEvent {
    pub fingerprint: String,
    pub exceptions: Vec<Exception>,
    pub handled: bool,
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
            event: IssueEvent {
                fingerprint: "abc".to_string(),
                exceptions: vec![Exception {
                    exception_id: None,
                    exception_type: "TypeError".to_string(),
                    exception_message: "x is not a function".to_string(),
                    mechanism: None,
                    module: None,
                    thread_id: None,
                    stack: None,
                }],
                handled: false,
            },
            event_timestamp: DateTime::from_timestamp(0, 0).unwrap(),
        });

        let json = serde_json::to_value(&notification).unwrap();
        assert_eq!(json["type"], "issue_created");
        assert_eq!(json["team_id"], 42);
        assert_eq!(json["event"]["fingerprint"], "abc");
        assert_eq!(json["event"]["exceptions"][0]["type"], "TypeError");

        // Round-trips back to the same JSON through the typed enum.
        let decoded: IngestionNotification = serde_json::from_value(json.clone()).unwrap();
        assert_eq!(serde_json::to_value(&decoded).unwrap(), json);
    }
}
