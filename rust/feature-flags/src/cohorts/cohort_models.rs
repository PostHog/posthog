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
    pub cohort_type: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum CohortType {
    Static,
    PersonProperty,
    Behavioral,
    Analytical,
}

impl Cohort {
    pub fn get_cohort_type(&self) -> CohortType {
        if let Some(ref cohort_type) = self.cohort_type {
            match cohort_type.as_str() {
                "static" => CohortType::Static,
                "person_property" => CohortType::PersonProperty,
                "behavioral" => CohortType::Behavioral,
                "analytical" => CohortType::Analytical,
                _ => self.determine_legacy_type(),
            }
        } else {
            self.determine_legacy_type()
        }
    }

    fn determine_legacy_type(&self) -> CohortType {
        if self.is_static {
            CohortType::Static
        } else {
            // For backward compatibility, treat all dynamic cohorts as PersonProperty
            // This matches current behavior where only simple cohorts work in flags
            CohortType::PersonProperty
        }
    }

    pub fn can_be_used_in_feature_flag(&self) -> bool {
        match self.get_cohort_type() {
            CohortType::Static | CohortType::PersonProperty => true,
            CohortType::Behavioral | CohortType::Analytical => false,
        }
    }
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
