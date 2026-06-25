//! The wire contract for the `error_tracking_ingestion_notifications` Kafka
//! topic. The processing mode produces these; the notifications mode consumes
//! them.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::types::OutputErrProps;

/// A notification emitted by error-tracking ingestion. Serialized as
/// internally-tagged JSON (`{"type": "issue_created", ...}`) so new variants can
/// be added without breaking existing consumers — an unknown `type` simply fails
/// to deserialize and is skipped as a poison pill.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum IngestionNotification {
    /// A new issue was created during ingestion.
    IssueCreated(IssueCreated),
    /// A resolved issue was reopened during ingestion.
    IssueReopened(IssueReopened),
    /// An issue crossed the spike threshold during ingestion.
    IssueSpiking(IssueSpiking),
}

impl IngestionNotification {
    pub fn partition_key(&self) -> String {
        match self {
            IngestionNotification::IssueCreated(issue_created) => {
                format!("{}:{}", issue_created.team_id, issue_created.issue_id)
            }
            IngestionNotification::IssueReopened(issue_reopened) => {
                format!("{}:{}", issue_reopened.team_id, issue_reopened.issue_id)
            }
            IngestionNotification::IssueSpiking(issue_spiking) => {
                format!("{}:{}", issue_spiking.team_id, issue_spiking.issue_id)
            }
        }
    }
}

/// Payload for [`IngestionNotification::IssueCreated`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueCreated {
    /// Stable id for retryable side effects produced from this notification.
    #[serde(default = "Uuid::now_v7")]
    pub notification_id: Uuid,
    pub team_id: i32,
    pub issue_id: Uuid,
    pub fingerprint: String,
    pub event_uuid: Uuid,
    pub event_timestamp: String,
    pub assignee: Option<String>,
    /// Full final exception event properties after Cymbal processing.
    pub event_properties: OutputErrProps,
}

/// Payload for [`IngestionNotification::IssueReopened`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueReopened {
    /// Stable id for retryable side effects produced from this notification.
    #[serde(default = "Uuid::now_v7")]
    pub notification_id: Uuid,
    pub team_id: i32,
    pub issue_id: Uuid,
    pub event_timestamp: String,
    pub assignee: Option<String>,
    /// Full final exception event properties after Cymbal processing.
    pub event_properties: OutputErrProps,
}

/// Payload for [`IngestionNotification::IssueSpiking`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueSpiking {
    /// Stable id for retryable side effects produced from this notification.
    #[serde(default = "Uuid::now_v7")]
    pub notification_id: Uuid,
    pub team_id: i32,
    pub issue_id: Uuid,
    pub computed_baseline: f64,
    pub current_bucket_value: f64,
    /// Full final exception event properties after Cymbal processing.
    pub event_properties: OutputErrProps,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn issue_created_round_trips_with_type_tag() {
        let notification = IngestionNotification::IssueCreated(IssueCreated {
            notification_id: Uuid::nil(),
            team_id: 42,
            issue_id: Uuid::nil(),
            fingerprint: "abc".to_string(),
            event_uuid: Uuid::nil(),
            event_timestamp: "1970-01-01T00:00:00Z".to_string(),
            assignee: None,
            event_properties: OutputErrProps {
                fingerprint: "abc".to_string(),
                ..Default::default()
            },
        });

        let json = serde_json::to_value(&notification).unwrap();
        assert_eq!(json["type"], "issue_created");
        assert_eq!(json["team_id"], 42);
        assert_eq!(json["fingerprint"], "abc");
        assert_eq!(json["event_properties"]["$exception_fingerprint"], "abc");

        // Round-trips back to the same JSON through the typed enum.
        let decoded: IngestionNotification = serde_json::from_value(json.clone()).unwrap();
        assert_eq!(serde_json::to_value(&decoded).unwrap(), json);
    }
}
