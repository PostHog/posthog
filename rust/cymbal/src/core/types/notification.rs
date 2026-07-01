//! The wire contract for the `error_tracking_ingestion_notifications` Kafka
//! topic. The processing mode produces these; the notifications mode consumes
//! them.

use chrono::{DateTime, Utc};
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
    pub fn notification_id(&self) -> Uuid {
        match self {
            IngestionNotification::IssueCreated(issue_created) => {
                issue_created.meta.notification_id
            }
            IngestionNotification::IssueReopened(issue_reopened) => {
                issue_reopened.meta.notification_id
            }
            IngestionNotification::IssueSpiking(issue_spiking) => {
                issue_spiking.meta.notification_id
            }
        }
    }

    pub fn team_id(&self) -> i32 {
        match self {
            IngestionNotification::IssueCreated(issue_created) => issue_created.meta.team_id,
            IngestionNotification::IssueReopened(issue_reopened) => issue_reopened.meta.team_id,
            IngestionNotification::IssueSpiking(issue_spiking) => issue_spiking.meta.team_id,
        }
    }

    pub fn partition_key(&self) -> String {
        match self {
            IngestionNotification::IssueCreated(issue_created) => {
                issue_created.issue.partition_key(self.team_id())
            }
            IngestionNotification::IssueReopened(issue_reopened) => {
                issue_reopened.issue.partition_key(self.team_id())
            }
            IngestionNotification::IssueSpiking(issue_spiking) => {
                issue_spiking.issue.partition_key(self.team_id())
            }
        }
    }
}

/// Shared metadata for every ingestion notification.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NotificationMeta {
    /// Stable id for retryable side effects produced from this notification.
    #[serde(default = "Uuid::now_v7")]
    pub notification_id: Uuid,
    pub team_id: i32,
}

/// Shared context for notifications that produce issue side effects.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueNotificationContext {
    pub issue_id: Uuid,
    pub issue: IssueSnapshot,
    /// Full final exception event properties after Cymbal processing.
    pub event_properties: OutputErrProps,
}

impl IssueNotificationContext {
    pub fn partition_key(&self, team_id: i32) -> String {
        format!("{}:{}", team_id, self.issue_id)
    }
}

/// Payload for [`IngestionNotification::IssueCreated`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueCreated {
    #[serde(flatten)]
    pub meta: NotificationMeta,
    #[serde(flatten)]
    pub issue: IssueNotificationContext,
    pub fingerprint: String,
    pub event_uuid: Uuid,
    pub event_timestamp: String,
    pub assignee: Option<String>,
}

/// Payload for [`IngestionNotification::IssueReopened`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueReopened {
    #[serde(flatten)]
    pub meta: NotificationMeta,
    #[serde(flatten)]
    pub issue: IssueNotificationContext,
    pub event_timestamp: String,
    pub assignee: Option<String>,
}

/// Payload for [`IngestionNotification::IssueSpiking`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueSpiking {
    #[serde(flatten)]
    pub meta: NotificationMeta,
    #[serde(flatten)]
    pub issue: IssueNotificationContext,
    pub computed_baseline: f64,
    pub current_bucket_value: f64,
}

/// Issue state captured when the ingestion transition happened.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueSnapshot {
    pub name: Option<String>,
    pub description: Option<String>,
    pub status: String,
    pub created_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn issue_created_round_trips_with_type_tag() {
        let notification = IngestionNotification::IssueCreated(IssueCreated {
            meta: NotificationMeta {
                notification_id: Uuid::nil(),
                team_id: 42,
            },
            issue: IssueNotificationContext {
                issue_id: Uuid::nil(),
                issue: IssueSnapshot {
                    name: Some("Example".to_string()),
                    description: Some("Example issue".to_string()),
                    status: "active".to_string(),
                    created_at: DateTime::from_timestamp(0, 0).unwrap(),
                },
                event_properties: OutputErrProps {
                    fingerprint: "abc".to_string(),
                    ..Default::default()
                },
            },
            fingerprint: "abc".to_string(),
            event_uuid: Uuid::nil(),
            event_timestamp: "1970-01-01T00:00:00Z".to_string(),
            assignee: None,
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
