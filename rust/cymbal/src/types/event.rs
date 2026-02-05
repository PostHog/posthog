use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    fingerprinting::FingerprintRecordPart, frames::releases::ReleaseInfo, issue_resolution::Issue,
    types::ExceptionList,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExceptionProperties {
    #[serde(rename = "$exception_list")]
    pub exception_list: ExceptionList,

    #[serde(rename = "$exception_sources")]
    pub exception_sources: Option<Vec<String>>,
    #[serde(rename = "$exception_types")]
    pub exception_types: Option<Vec<String>>,
    #[serde(rename = "$exception_messages")]
    pub exception_messages: Option<Vec<String>>,
    #[serde(rename = "$exception_functions")]
    pub exception_functions: Option<Vec<String>>,
    #[serde(rename = "$exception_handled")]
    pub exception_handled: Option<bool>,

    #[serde(
        rename = "$exception_releases",
        skip_serializing_if = "HashMap::is_empty",
        default
    )]
    pub releases: HashMap<String, ReleaseInfo>,

    #[serde(rename = "$exception_fingerprint")]
    pub fingerprint: Option<String>,
    #[serde(rename = "$exception_proposed_fingerprint")]
    pub proposed_fingerprint: Option<String>,
    #[serde(rename = "$exception_fingerprint_record")]
    pub fingerprint_record: Option<Vec<FingerprintRecordPart>>,

    #[serde(rename = "$exception_issue_id")]
    pub issue_id: Option<Uuid>,
    #[serde(rename = "$issue_name", skip_serializing_if = "Option::is_none")]
    pub proposed_issue_name: Option<String>,
    #[serde(rename = "$issue_description", skip_serializing_if = "Option::is_none")]
    pub proposed_issue_description: Option<String>,

    #[serde(flatten)]
    pub props: HashMap<String, Value>,

    // Metadata used for ingestion
    #[serde(skip)]
    pub uuid: Uuid,

    #[serde(skip)]
    pub timestamp: String,

    #[serde(skip)]
    pub team_id: i32,

    #[serde(skip)]
    pub issue: Option<Issue>,
}
