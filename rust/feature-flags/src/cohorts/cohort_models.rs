use crate::properties::property_models::PropertyFilter;
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct Cohort {
    pub id: i32,
    pub name: Option<String>,
    pub description: Option<String>,
    pub team_id: i32,
    pub deleted: bool,
    pub filters: Option<serde_json::Value>,
    pub query: Option<serde_json::Value>,
    pub version: Option<i32>,
    pub pending_version: Option<i32>,
    pub count: Option<i32>,
    pub is_calculating: bool,
    pub is_static: bool,
    pub errors_calculating: i32,
    pub groups: serde_json::Value,
    pub created_by_id: Option<i32>,
}

pub type CohortId = i32;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum CohortPropertyType {
    AND,
    OR,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CohortProperty {
    pub properties: InnerCohortProperty,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct InnerCohortProperty {
    #[serde(rename = "type")]
    pub prop_type: CohortPropertyType,
    pub values: Vec<CohortValues>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CohortValues {
    #[serde(rename = "type")]
    pub prop_type: String,
    pub values: Vec<PropertyFilter>,
}
