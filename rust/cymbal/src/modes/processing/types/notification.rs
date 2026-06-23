//! The wire contract for the `error-tracking-ingestion-notifications` Kafka
//! topic. The processing mode produces these; the notifications mode consumes
//! them. Lives alongside the processing event model because it embeds the full
//! emitted exception event ([`OutputErrProps`]), which is processing-owned and
//! therefore cannot live in `core`.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::issue_resolution::Issue;
use crate::modes::processing::types::OutputErrProps;

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
    /// The full symbolicated exception event that triggered issue creation —
    /// the same output properties emitted to the rest of the pipeline.
    pub event: OutputErrProps,
    /// Timestamp of the originating exception event (distinct from the issue's
    /// `created_at`).
    pub event_timestamp: DateTime<Utc>,
}

impl IngestionNotification {
    /// Build an [`IngestionNotification::IssueCreated`] from a freshly created
    /// issue and the exception event that triggered it.
    pub fn issue_created(
        issue: &Issue,
        event: OutputErrProps,
        event_timestamp: DateTime<Utc>,
    ) -> Self {
        Self::IssueCreated(IssueCreated {
            team_id: issue.team_id,
            issue_id: issue.id,
            name: issue.name.clone(),
            description: issue.description.clone(),
            created_at: issue.created_at,
            event,
            event_timestamp,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn issue_created_round_trips_with_type_tag() {
        let mut event = OutputErrProps::default();
        event.fingerprint = "abc".to_string();

        let notification = IngestionNotification::IssueCreated(IssueCreated {
            team_id: 42,
            issue_id: Uuid::nil(),
            name: Some("TypeError".to_string()),
            description: None,
            created_at: DateTime::from_timestamp(0, 0).unwrap(),
            event,
            event_timestamp: DateTime::from_timestamp(0, 0).unwrap(),
        });

        let json = serde_json::to_value(&notification).unwrap();
        assert_eq!(json["type"], "issue_created");
        assert_eq!(json["team_id"], 42);
        assert_eq!(json["event"]["$exception_fingerprint"], "abc");

        // Round-trips back to the same JSON through the typed enum.
        let decoded: IngestionNotification = serde_json::from_value(json.clone()).unwrap();
        assert_eq!(serde_json::to_value(&decoded).unwrap(), json);
    }
}
