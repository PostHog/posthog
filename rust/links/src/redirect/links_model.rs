use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct LinkRow {
    pub id: String,
    pub destination: String,
    pub origin_domain: String,
    pub origin_key: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub description: String,
    pub team_id: i32,
}
