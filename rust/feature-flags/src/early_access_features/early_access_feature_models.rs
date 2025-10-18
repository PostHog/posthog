use serde::{Deserialize, Serialize};
use sqlx::FromRow;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum EarlyAccessStage {
    #[serde(rename = "draft")]
    Draft,
    #[serde(rename = "concept")]
    Concept,
    #[serde(rename = "alpha")]
    Alpha,
    #[serde(rename = "beta")]
    Beta,
    #[serde(rename = "general-availability")]
    GeneralAvailability,
    #[serde(rename = "archived")]
    Archived,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct EarlyAccessFeature {
    pub id: i32,
    pub team_id: Option<i32>,
    pub feature_flag_id: Option<i32>,
    pub name: String,
    pub description: String,
    pub stage: EarlyAccessStage,
}