//! Notification records shared by the broker and the native window.
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

/// Broker route for approval conditions.
pub const APPROVALS: &str = "$approvals";

/// Source of a notification.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum Producer {
    /// An approval request.
    Approval,
    /// A view or its SDK.
    View,
    /// A scheduled reminder.
    Reminder,
    /// A workflow run.
    Workflow,
    /// A view access request.
    Access,
    /// A connected service.
    Connection,
    /// A topic produced this notification.
    Topic,
}

/// How the notification is updated and dismissed.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum Lifecycle {
    /// A condition that can change or recover.
    Condition,
    /// A delivered message with read state.
    Message,
}

/// Attention level presented to the reader.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum Level {
    /// Needs a decision or intervention.
    NeedsYou,
    /// Informational update.
    Info,
    /// Successful outcome or recovery.
    Success,
}

/// What initiated the notification.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum Origin {
    /// Raised by background work.
    Background,
    /// Raised in response to a user action.
    UserAction,
}

/// An action offered by a notification.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub enum Action {
    /// Open a view and optionally invoke a command.
    Open {
        /// Target view identifier.
        view: String,
        /// Command to run after opening the view.
        command: Option<String>,
        /// Arguments supplied to the command.
        args: Value,
    },
    /// Open an approval request.
    Review {
        /// Approval to review.
        approval: ApprovalRef,
    },
    /// Retry a workflow in its view.
    Retry {
        /// Target view identifier.
        view: String,
        /// Workflow identifier.
        workflow: String,
    },
    /// Open a particular workflow step.
    ShowStep {
        /// Target view identifier.
        view: String,
        /// Workflow identifier.
        workflow: String,
        /// Step identifier within the workflow.
        step: String,
    },
    /// Review a capability grant for a view.
    Allow {
        /// Target view identifier.
        view: String,
        /// Capability requested by the view.
        capability: String,
    },
    /// Reconnect an account.
    Reconnect {
        /// Connection identifier.
        connection: String,
        /// Display name of the connection.
        name: String,
    },
}

/// Identity of the request opened by a review action.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum ApprovalRef {
    /// A request made by an agent session.
    Agent {
        /// Session that requested approval.
        session: String,
        /// Request identifier.
        id: String,
    },
    /// A request made by a view.
    View {
        /// Request identifier.
        id: String,
    },
}

/// A broker notification and its delivery state.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
pub struct Notification {
    /// Stable broker identifier.
    pub key: String,
    /// Source that emitted this record.
    pub producer: Producer,
    /// The topic that owns this notification, independent of its producer.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub topic: Option<String>,
    /// View associated with this notification, when present.
    pub view_id: Option<String>,
    /// Identifiers of additional affected items.
    pub affects: Vec<String>,
    /// Whether this tracks a condition or delivers a message.
    pub lifecycle: Lifecycle,
    /// Attention level used for presentation.
    pub level: Level,
    /// Short notification title.
    pub title: String,
    /// Optional explanatory text.
    pub detail: Option<String>,
    /// Available actions in display order.
    pub actions: Vec<Action>,
    /// Identifier of the originating cause, when known.
    pub cause: Option<String>,
    /// Value used to recognize repeated occurrences.
    pub fingerprint: Option<String>,
    /// Workflow failure classification, when applicable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failure_kind: Option<meep_workflows::FailureKind>,
    /// Number of occurrences represented by this record.
    pub count: u32,
    /// Time of the first occurrence.
    pub since: DateTime<Utc>,
    /// Time of the latest update.
    pub updated: DateTime<Utc>,
    /// Time the message was marked read.
    pub read: Option<DateTime<Utc>>,
    /// Muted state recorded by the broker.
    pub muted: Option<String>,
    /// Whether background work or a user action initiated the record.
    pub origin: Origin,
    /// Keeps the SDK's original entry shape and delivery options.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub view_payload: Option<Value>,
}

impl Notification {
    /// Build a message from a View SDK payload.
    pub fn message(view: &str, payload: Value, producer: Producer) -> Self {
        let id = payload["id"].as_str().unwrap_or_default();
        let updated =
            serde_json::from_value(payload["createdAt"].clone()).unwrap_or_else(|_| Utc::now());
        Self {
            key: message_key(view, id),
            producer,
            topic: None,
            view_id: Some(view.into()),
            affects: vec![],
            lifecycle: Lifecycle::Message,
            level: Level::Info,
            title: payload["title"].as_str().unwrap_or_default().into(),
            detail: payload["body"].as_str().map(str::to_owned),
            actions: vec![Action::Open {
                view: view.into(),
                command: payload["action"]["command"].as_str().map(str::to_owned),
                args: payload["action"]["args"].clone(),
            }],
            cause: None,
            fingerprint: None,
            failure_kind: None,
            count: 1,
            since: updated,
            updated,
            read: None,
            muted: None,
            origin: Origin::Background,
            view_payload: Some(payload),
        }
    }

    /// Build a condition that opens the given approval.
    pub fn approval(
        view: &str,
        approval: ApprovalRef,
        title: &str,
        detail: &str,
        origin: Origin,
    ) -> Self {
        let id = match &approval {
            ApprovalRef::Agent { id, .. } | ApprovalRef::View { id } => id.clone(),
        };
        let now = Utc::now();
        Self {
            key: approval_key(&id),
            producer: Producer::Approval,
            topic: None,
            view_id: Some(view.into()),
            affects: vec![],
            lifecycle: Lifecycle::Condition,
            level: Level::NeedsYou,
            title: title.into(),
            detail: (!detail.is_empty()).then(|| detail.into()),
            actions: vec![Action::Review { approval }],
            cause: None,
            fingerprint: Some(id),
            failure_kind: None,
            count: 1,
            since: now,
            updated: now,
            read: None,
            muted: None,
            origin,
            view_payload: None,
        }
    }

    /// Build an actionable condition at a specified time.
    pub fn condition(
        key: String,
        producer: Producer,
        view_id: Option<String>,
        title: String,
        detail: String,
        action: Action,
        at: DateTime<Utc>,
    ) -> Self {
        Self {
            fingerprint: Some(key.clone()),
            key,
            producer,
            topic: None,
            view_id,
            affects: vec![],
            lifecycle: Lifecycle::Condition,
            level: Level::NeedsYou,
            title,
            detail: Some(detail),
            actions: vec![action],
            cause: None,
            failure_kind: None,
            count: 1,
            since: at,
            updated: at,
            read: None,
            muted: None,
            origin: Origin::Background,
            view_payload: None,
        }
    }

    /// Build a success message for a recovered workflow.
    pub fn recovery(view: &str, id: &str, title: &str, at: DateTime<Utc>) -> Self {
        let mut record = Self::message(
            view,
            json!({"title":format!("{title} works again"),"createdAt":at}),
            Producer::Workflow,
        );
        record.key = format!("workflow-recovered:{view}:{id}");
        record.level = Level::Success;
        record.view_payload = None;
        record
    }

    /// Return the route and identifier used when opening an OS notification.
    pub fn os_target(&self) -> Option<(&str, &str)> {
        match self.lifecycle {
            Lifecycle::Condition => Some((
                if self.producer == Producer::Approval {
                    APPROVALS
                } else {
                    "$notifications"
                },
                &self.key,
            )),
            Lifecycle::Message => Some((
                self.view_id.as_deref()?,
                self.view_payload.as_ref()?["id"].as_str()?,
            )),
        }
    }

    /// Whether this is a message awaiting its first read.
    pub fn unread(&self) -> bool {
        self.lifecycle == Lifecycle::Message && self.read.is_none()
    }
}

/// Encode a view and its SDK message ID as a single broker key.
pub fn message_key(view: &str, id: &str) -> String {
    // View IDs and SDK IDs are opaque. Encode the pair without delimiter collisions.
    format!("view:{}", json!([view, id]))
}

/// Broker key for an approval identifier.
pub fn approval_key(id: &str) -> String {
    format!("approval:{id}")
}

/// Notifications to insert, replace, or remove in one update.
#[derive(Debug, Deserialize, Serialize)]
pub struct Change {
    /// Records to insert or replace by key.
    pub upserts: Vec<Notification>,
    /// Keys of records to remove.
    pub removals: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saved_view_and_access_notifications_keep_their_producer_and_target() -> serde_json::Result<()>
    {
        for producer in ["View", "Access"] {
            let wire = json!({
                "key": "legacy", "producer": producer, "view_id": "weekly", "affects": [],
                "lifecycle": "Message", "level": "Info", "title": "Report ready",
                "detail": null, "actions": [], "cause": null, "fingerprint": null,
                "count": 1, "since": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z",
                "read": null, "muted": null, "origin": "Background", "view_payload": {"id": "report"}
            });
            let notice: Notification = serde_json::from_value(wire)?;
            assert_eq!(notice.topic, None);
            assert_eq!(notice.os_target(), Some(("weekly", "report")));
            assert_eq!(serde_json::to_value(notice.producer)?, producer);
        }
        Ok(())
    }
}
