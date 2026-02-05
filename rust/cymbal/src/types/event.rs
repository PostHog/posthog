use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    fingerprinting::FingerprintRecordPart, frames::releases::ReleaseInfo, issue_resolution::Issue,
    types::ExceptionList,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExceptionEvent {
    pub uuid: Uuid,
    pub timestamp: String,
    pub team_id: i32,
    pub event: String,

    pub exception_list: ExceptionList,

    pub exception_sources: Option<Vec<String>>,
    pub exception_types: Option<Vec<String>>,
    pub exception_messages: Option<Vec<String>>,
    pub exception_functions: Option<Vec<String>>,
    pub exception_handled: Option<bool>,

    pub releases: HashMap<String, ReleaseInfo>,

    #[serde(rename = "$exception_fingerprint")]
    pub fingerprint: Option<String>,
    #[serde(rename = "$exception_proposed_fingerprint")]
    pub proposed_fingerprint: Option<String>,
    #[serde(rename = "$exception_fingerprint_record")]
    pub fingerprint_record: Option<Vec<FingerprintRecordPart>>,

    pub issue_id: Option<Uuid>,
    pub proposed_issue_name: Option<String>,
    pub proposed_issue_description: Option<String>,

    #[serde(flatten)]
    pub props: HashMap<String, Value>,

    #[serde(skip)]
    pub issue: Option<Issue>,
}
