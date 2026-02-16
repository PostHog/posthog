use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    error::UnhandledError,
    fingerprinting::FingerprintRecordPart,
    frames::releases::ReleaseInfo,
    issue_resolution::Issue,
    types::{ExceptionList, OutputErrProps},
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
    pub exception_releases: HashMap<String, ReleaseInfo>,

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

impl ExceptionProperties {
    pub fn to_output(&self, issue_id: Uuid) -> Result<OutputErrProps, UnhandledError> {
        // Extract metadata from exception list
        let types = self
            .exception_types
            .clone()
            .ok_or_else(|| UnhandledError::Other("Missing exception types".into()))?;
        let values = self
            .exception_messages
            .clone()
            .ok_or_else(|| UnhandledError::Other("Missing exception messages".into()))?;
        let sources = self
            .exception_sources
            .clone()
            .ok_or_else(|| UnhandledError::Other("Missing exception sources".into()))?;
        let functions = self
            .exception_functions
            .clone()
            .ok_or_else(|| UnhandledError::Other("Missing exception functions".into()))?;
        let releases = self.exception_releases.clone();
        let handled = self
            .exception_handled
            .ok_or_else(|| UnhandledError::Other("Missing exception handled status".into()))?;
        let fingerprint = self
            .fingerprint
            .clone()
            .ok_or_else(|| UnhandledError::Other("Missing fingerprint".into()))?;
        let proposed_fingerprint = self
            .proposed_fingerprint
            .clone()
            .ok_or_else(|| UnhandledError::Other("Missing proposed_fingerprint".into()))?;

        Ok(OutputErrProps {
            exception_list: self.exception_list.clone(),
            fingerprint,
            proposed_fingerprint,
            fingerprint_record: self.fingerprint_record.clone().unwrap_or_default(),
            issue_id,
            other: self.props.clone(),
            handled,
            releases,
            types,
            values,
            sources,
            functions,
        })
    }
}
