use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct LinkRow {
    pub id: Uuid,
    pub redirect_url: String,
    pub short_link_domain: String,
    pub short_code: String,
    pub created_at: DateTime<Utc>,
    pub description: String,
    pub team: i32,
}
