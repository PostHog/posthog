//! The wire contract for the `error-tracking-ingestion-notifications` Kafka
//! topic. The processing mode produces these; the notifications mode consumes
//! them.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::core::types::event::AnyEvent;

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
    /// Fingerprint that created this issue.
    pub fingerprint: String,
    /// The full symbolicated exception event that triggered issue creation.
    pub event: AnyEvent,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn issue_created_round_trips_with_type_tag() {
        let notification = IngestionNotification::IssueCreated(IssueCreated {
            team_id: 42,
            issue_id: Uuid::nil(),
            fingerprint: "abc".to_string(),
            event: AnyEvent {
                uuid: Uuid::nil(),
                event: "$exception".to_string(),
                team_id: 42,
                timestamp: "1970-01-01T00:00:00Z".to_string(),
                properties: serde_json::json!({ "$exception_fingerprint": "abc" }),
                others: Default::default(),
            },
        });

        let json = serde_json::to_value(&notification).unwrap();
        assert_eq!(json["type"], "issue_created");
        assert_eq!(json["team_id"], 42);
        assert_eq!(json["fingerprint"], "abc");
        assert_eq!(json["event"]["properties"]["$exception_fingerprint"], "abc");

        // Round-trips back to the same JSON through the typed enum.
        let decoded: IngestionNotification = serde_json::from_value(json.clone()).unwrap();
        assert_eq!(serde_json::to_value(&decoded).unwrap(), json);
    }
}
