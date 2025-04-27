use chrono::{DateTime, Utc};
use serde::Serialize;
use uuid::Uuid;

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct PersonalAPIKey {
    pub id: String,
    pub label: String,
    pub value: Option<String>,
    pub secure_value: Option<String>,
    pub created_at: DateTime<Utc>,
    pub last_used_at: Option<DateTime<Utc>>,
    pub team_id: Option<i32>,
    pub organization_id: Uuid,
    pub user_id: i32,
    pub scoped_organizations: Vec<String>,
    pub scoped_teams: Vec<i32>,
    pub scopes: Vec<String>,
    pub mask_value: String,
}
