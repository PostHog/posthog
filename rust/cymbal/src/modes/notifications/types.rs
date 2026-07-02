use chrono::{DateTime, Utc};
use uuid::Uuid;

pub trait NotificationIssue {
    fn id(&self) -> Uuid;
    fn team_id(&self) -> i32;
    fn name(&self) -> Option<&str>;
    fn description(&self) -> Option<&str>;
    fn status(&self) -> &str;
    fn created_at(&self) -> DateTime<Utc>;
}

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct IssueNotificationData {
    pub id: Uuid,
    pub team_id: i32,
    pub status: String,
    pub name: Option<String>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
}

impl NotificationIssue for IssueNotificationData {
    fn id(&self) -> Uuid {
        self.id
    }

    fn team_id(&self) -> i32 {
        self.team_id
    }

    fn name(&self) -> Option<&str> {
        self.name.as_deref()
    }

    fn description(&self) -> Option<&str> {
        self.description.as_deref()
    }

    fn status(&self) -> &str {
        match self.status.as_str() {
            "archived" => "Archived",
            "active" => "Active",
            "resolved" => "Resolved",
            "pending_release" => "Pending Release",
            "suppressed" => "Suppressed",
            _ => &self.status,
        }
    }

    fn created_at(&self) -> DateTime<Utc> {
        self.created_at
    }
}
