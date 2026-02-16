use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    fingerprinting::FingerprintRecordPart,
    frames::releases::ReleaseInfo,
    issue_resolution::Issue,
    recursively_sanitize_properties,
    types::{event::AnyEvent, ExceptionList, OutputErrProps},
};

pub const MAX_EXCEPTION_VALUE_LENGTH: usize = 10_000;

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

impl TryFrom<AnyEvent> for ExceptionProperties {
    type Error = EventError;

    fn try_from(event: AnyEvent) -> Result<Self, Self::Error> {
        if event.event != "$exception" {
            return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
        }

        let mut properties: Value = match serde_json::from_value(event.properties) {
            Ok(r) => r,
            Err(e) => {
                return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
            }
        };

        if let Some(v) = properties
            .as_object_mut()
            .and_then(|o| o.get_mut("$exception_list"))
        {
            // We PG sanitize the exception list, because the strings in it can end up in PG kind of arbitrarily.
            // TODO - the prep stage has already sanitized the properties, so maybe we don't need to do this again?
            recursively_sanitize_properties(event.uuid, v, 0)?;
        }

        let mut evt: ExceptionProperties = match serde_json::from_value(properties) {
            Ok(r) => r,
            Err(e) => {
                return Err(EventError::InvalidProperties(event.uuid, e.to_string()));
            }
        };

        if evt.exception_list.is_empty() {
            return Err(EventError::EmptyExceptionList(event.uuid));
        }

        for exception in evt.exception_list.iter_mut() {
            if exception.exception_message.len() > MAX_EXCEPTION_VALUE_LENGTH {
                let truncate_at = exception
                    .exception_message
                    .char_indices()
                    .take_while(|(i, _)| *i < MAX_EXCEPTION_VALUE_LENGTH)
                    .last()
                    .map(|(i, c)| i + c.len_utf8())
                    .unwrap_or(0);
                exception.exception_message.truncate(truncate_at);
                exception.exception_message.push_str("...");
            }
            exception.exception_id = Some(Uuid::now_v7().to_string());
        }

        // Set metadata fields that are skipped during deserialization
        evt.uuid = event.uuid;
        evt.timestamp = event.timestamp;
        evt.team_id = event.team_id;

        Ok(evt)
    }
}
