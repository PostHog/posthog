use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct EarlyAccessFeature {
    pub id: Uuid,
    pub team_id: Option<i32>,
    pub feature_flag_id: Option<i32>,
    pub name: String,
    pub description: String,
    // This is not an enum because models.TextChoices is stored as string in the db
    pub stage: String,
    pub documentation_url: String,
}