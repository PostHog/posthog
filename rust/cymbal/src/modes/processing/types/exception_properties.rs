use std::collections::HashMap;

use common_types::ClickHouseEvent;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::{
    error::{EventError, UnhandledError},
    fingerprinting::FingerprintRecordPart,
    frames::releases::ReleaseInfo,
    issue_resolution::Issue,
    langs::native::DebugImage,
    modes::processing::normalization::normalize_wire_order,
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
    #[serde(rename = "$exception_values")]
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

    #[serde(
        rename = "$debug_images",
        default,
        skip_serializing_if = "Vec::is_empty"
    )]
    pub debug_images: Vec<DebugImage>,

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

    // The raw exception list in its original (pre-normalization) wire order,
    // set only when wire-order normalization reversed frames and/or the list at
    // ingest. Resolution resolves it alongside the canonical list (cache-warm,
    // so cheap) so grouping can compute the legacy-order fingerprint for issue
    // continuity. Cleared once resolution has produced the resolved copy below.
    #[serde(skip)]
    pub legacy_order_exception_list: Option<ExceptionList>,

    // The resolved exception list in legacy wire order, populated by the
    // resolution stage when `legacy_order_exception_list` was set. The grouping
    // stage fingerprints it and clears it.
    #[serde(skip)]
    pub legacy_order_resolved: Option<ExceptionList>,

    // The fingerprint the event would have produced in its original
    // (pre-normalization) order. `Some` only when normalization was applied and
    // the grouping stage computed it. Consumed by issue linking for continuity.
    #[serde(skip)]
    pub legacy_fingerprint: Option<String>,
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

        // `event.properties` is already a `serde_json::Value`; running it back through
        // `from_value` only deep-rebuilds the tree. Take ownership directly instead.
        let mut properties = event.properties;

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

        // Normalize incoming wire order (frames / exception list) per $lib so
        // fingerprinting and resolution downstream see canonical order. Runs
        // after exception ids are assigned so the legacy snapshot shares ids
        // with the canonical list. Reading $lib/$lib_version from `props` — the
        // flatten catch-all where non-exception event properties land.
        let lib = evt.props.get("$lib").and_then(Value::as_str);
        let lib_version = evt.props.get("$lib_version").and_then(Value::as_str);
        evt.legacy_order_exception_list =
            normalize_wire_order(&mut evt.exception_list, lib, lib_version);

        // Set metadata fields that are skipped during deserialization
        evt.uuid = event.uuid;
        evt.timestamp = event.timestamp;
        evt.team_id = event.team_id;

        Ok(evt)
    }
}

impl TryFrom<ClickHouseEvent> for ExceptionProperties {
    type Error = EventError;

    fn try_from(event: ClickHouseEvent) -> Result<Self, Self::Error> {
        let any_evt = AnyEvent::try_from(event)?;
        ExceptionProperties::try_from(any_evt)
    }
}

impl TryFrom<Result<ClickHouseEvent, EventError>> for ExceptionProperties {
    type Error = EventError;

    fn try_from(event: Result<ClickHouseEvent, EventError>) -> Result<Self, Self::Error> {
        match event {
            Ok(evt) => ExceptionProperties::try_from(evt),
            Err(e) => Err(e),
        }
    }
}
