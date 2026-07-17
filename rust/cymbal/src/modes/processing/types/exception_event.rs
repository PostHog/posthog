use std::collections::HashMap;

use common_types::ClickHouseEvent;
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::{
    error::EventError,
    fingerprinting::{FingerprintRecordPart, FingerprintVersion},
    frames::releases::ReleaseInfo,
    issue_resolution::Issue,
    langs::native::DebugImage,
    modes::processing::normalization::normalize_wire_order,
    recursively_sanitize_properties,
    types::{event::AnyEvent, ExceptionList, OutputErrProps, RawErrProps},
};

pub const MAX_EXCEPTION_VALUE_LENGTH: usize = 10_000;

pub type PipelineItem<S> = Result<ExceptionEvent<S>, EventError>;

#[derive(Debug, Clone)]
pub struct Parsed {
    pub(crate) client_fingerprint: Option<String>,
    pub(crate) legacy_order_exception_list: Option<ExceptionList>,
    pub(crate) legacy_order_resolved: Option<ExceptionList>,
}

#[derive(Debug, Clone)]
pub struct ResolvedMetadata {
    pub sources: Vec<String>,
    pub types: Vec<String>,
    pub messages: Vec<String>,
    pub functions: Vec<String>,
    pub handled: bool,
    pub releases: HashMap<String, ReleaseInfo>,
}

impl ResolvedMetadata {
    fn from_exception_list(exception_list: &ExceptionList) -> Self {
        Self {
            sources: exception_list.get_unique_sources(),
            types: exception_list.get_unique_types(),
            messages: exception_list.get_unique_messages(),
            functions: exception_list.get_unique_functions(),
            handled: exception_list.get_is_handled(),
            releases: exception_list.get_release_map(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct Resolved {
    pub(crate) metadata: ResolvedMetadata,
    pub(crate) client_fingerprint: Option<String>,
    pub(crate) legacy_order_resolved: Option<ExceptionList>,
}

#[derive(Debug, Clone)]
pub struct FingerprintData {
    pub value: String,
    pub version: Option<FingerprintVersion>,
    pub record: Vec<FingerprintRecordPart>,
}

#[derive(Debug, Clone)]
pub struct Fingerprinted {
    pub(crate) metadata: ResolvedMetadata,
    pub(crate) fingerprint: FingerprintData,
}

#[derive(Debug, Clone)]
pub struct Linked {
    pub(crate) metadata: ResolvedMetadata,
    pub(crate) fingerprint: FingerprintData,
    pub(crate) issue: Issue,
}

#[derive(Debug, Clone)]
pub struct RateChecked {
    linked: Linked,
}

#[derive(Debug, Clone)]
pub struct Finalized {
    linked: Linked,
}

#[derive(Debug, Clone)]
pub struct ExceptionEvent<S> {
    pub(crate) uuid: Uuid,
    pub(crate) team_id: i32,
    pub(crate) timestamp: String,
    pub(crate) exception_list: ExceptionList,
    pub(crate) debug_images: Vec<DebugImage>,
    pub(crate) props: HashMap<String, Value>,
    pub(crate) proposed_issue_name: Option<String>,
    pub(crate) proposed_issue_description: Option<String>,
    pub(crate) state: S,
}

impl<S> ExceptionEvent<S> {
    fn map_state<T>(self, transform: impl FnOnce(S) -> T) -> ExceptionEvent<T> {
        ExceptionEvent {
            uuid: self.uuid,
            team_id: self.team_id,
            timestamp: self.timestamp,
            exception_list: self.exception_list,
            debug_images: self.debug_images,
            props: self.props,
            proposed_issue_name: self.proposed_issue_name,
            proposed_issue_description: self.proposed_issue_description,
            state: transform(self.state),
        }
    }

    pub fn uuid(&self) -> Uuid {
        self.uuid
    }

    pub fn team_id(&self) -> i32 {
        self.team_id
    }

    pub fn timestamp(&self) -> &str {
        &self.timestamp
    }

    pub fn exception_list(&self) -> &ExceptionList {
        &self.exception_list
    }

    pub fn debug_images(&self) -> &[DebugImage] {
        &self.debug_images
    }

    pub fn properties(&self) -> &HashMap<String, Value> {
        &self.props
    }

    pub fn proposed_issue_name(&self) -> Option<&str> {
        self.proposed_issue_name.as_deref()
    }

    pub fn proposed_issue_description(&self) -> Option<&str> {
        self.proposed_issue_description.as_deref()
    }
}

impl ExceptionEvent<Parsed> {
    pub(crate) fn replace_exception_list(&mut self, exception_list: ExceptionList) {
        self.exception_list = exception_list;
    }

    pub(crate) fn take_legacy_order_exception_list(&mut self) -> Option<ExceptionList> {
        self.state.legacy_order_exception_list.take()
    }

    pub(crate) fn set_legacy_order_resolved(&mut self, exception_list: ExceptionList) {
        self.state.legacy_order_resolved = Some(exception_list);
    }

    pub(crate) fn into_resolved(self) -> ExceptionEvent<Resolved> {
        let metadata = ResolvedMetadata::from_exception_list(&self.exception_list);
        self.map_state(|state| Resolved {
            metadata,
            client_fingerprint: state.client_fingerprint,
            legacy_order_resolved: state.legacy_order_resolved,
        })
    }
}

impl ExceptionEvent<Resolved> {
    pub fn metadata(&self) -> &ResolvedMetadata {
        &self.state.metadata
    }

    pub(crate) fn client_fingerprint(&self) -> Option<&str> {
        self.state.client_fingerprint.as_deref()
    }

    pub(crate) fn take_legacy_order_resolved(&mut self) -> Option<ExceptionList> {
        self.state.legacy_order_resolved.take()
    }

    pub(crate) fn into_fingerprinted(
        self,
        fingerprint: FingerprintData,
    ) -> ExceptionEvent<Fingerprinted> {
        self.map_state(|state| Fingerprinted {
            metadata: state.metadata,
            fingerprint,
        })
    }

    pub fn to_grouping_value(&self) -> Value {
        let mut map = self.base_resolved_properties(&self.state.metadata);
        map.insert(
            "$exception_fingerprint".into(),
            self.state
                .client_fingerprint
                .as_ref()
                .map_or(Value::Null, |value| Value::String(value.clone())),
        );
        map.insert("$exception_fingerprint_record".into(), Value::Null);
        map.insert("$exception_issue_id".into(), Value::Null);
        Value::Object(map)
    }
}

impl ExceptionEvent<Fingerprinted> {
    pub fn metadata(&self) -> &ResolvedMetadata {
        &self.state.metadata
    }

    pub fn fingerprint(&self) -> &FingerprintData {
        &self.state.fingerprint
    }

    pub(crate) fn into_linked(self, issue: Issue) -> ExceptionEvent<Linked> {
        self.map_state(|state| Linked {
            metadata: state.metadata,
            fingerprint: state.fingerprint,
            issue,
        })
    }

    pub fn to_properties_value(&self) -> Value {
        self.properties_with_fingerprint(&self.state.metadata, &self.state.fingerprint, None)
    }

    pub fn to_output(&self, issue: &Issue) -> OutputErrProps {
        self.build_output(&self.state.metadata, &self.state.fingerprint, issue.id)
    }
}

impl ExceptionEvent<Linked> {
    pub fn metadata(&self) -> &ResolvedMetadata {
        &self.state.metadata
    }

    pub fn fingerprint(&self) -> &FingerprintData {
        &self.state.fingerprint
    }

    pub fn issue(&self) -> &Issue {
        &self.state.issue
    }

    pub fn issue_id(&self) -> Uuid {
        self.state.issue.id
    }

    pub fn to_output(&self) -> OutputErrProps {
        self.build_output(
            &self.state.metadata,
            &self.state.fingerprint,
            self.state.issue.id,
        )
    }

    pub fn to_properties_value(&self) -> Value {
        self.properties_with_fingerprint(
            &self.state.metadata,
            &self.state.fingerprint,
            Some(self.state.issue.id),
        )
    }

    pub(crate) fn into_rate_checked(self) -> ExceptionEvent<RateChecked> {
        self.map_state(|linked| RateChecked { linked })
    }
}

impl ExceptionEvent<RateChecked> {
    pub fn metadata(&self) -> &ResolvedMetadata {
        &self.state.linked.metadata
    }

    pub fn fingerprint(&self) -> &FingerprintData {
        &self.state.linked.fingerprint
    }

    pub fn issue(&self) -> &Issue {
        &self.state.linked.issue
    }

    pub fn issue_id(&self) -> Uuid {
        self.state.linked.issue.id
    }

    pub fn to_output(&self) -> OutputErrProps {
        self.build_output(
            &self.state.linked.metadata,
            &self.state.linked.fingerprint,
            self.state.linked.issue.id,
        )
    }

    pub(crate) fn into_finalized(self) -> ExceptionEvent<Finalized> {
        self.map_state(|state| Finalized {
            linked: state.linked,
        })
    }
}

impl ExceptionEvent<Finalized> {
    pub fn metadata(&self) -> &ResolvedMetadata {
        &self.state.linked.metadata
    }

    pub fn fingerprint(&self) -> &FingerprintData {
        &self.state.linked.fingerprint
    }

    pub fn issue(&self) -> &Issue {
        &self.state.linked.issue
    }

    pub fn issue_id(&self) -> Uuid {
        self.state.linked.issue.id
    }

    pub fn to_output(&self) -> OutputErrProps {
        self.build_output(
            &self.state.linked.metadata,
            &self.state.linked.fingerprint,
            self.state.linked.issue.id,
        )
    }

    pub fn to_clickhouse_value(&self) -> Value {
        let mut value = serde_json::to_value(self.to_output())
            .expect("final exception properties are serializable");
        let map = value
            .as_object_mut()
            .expect("serialized exception properties are an object");
        if let Some(name) = &self.proposed_issue_name {
            map.insert("$issue_name".into(), Value::String(name.clone()));
        }
        if let Some(description) = &self.proposed_issue_description {
            map.insert(
                "$issue_description".into(),
                Value::String(description.clone()),
            );
        }
        if !self.debug_images.is_empty() {
            map.insert(
                "$debug_images".into(),
                serde_json::to_value(&self.debug_images)
                    .expect("debug image properties are serializable"),
            );
        }
        value
    }
}

impl<S> ExceptionEvent<S> {
    fn base_resolved_properties(&self, metadata: &ResolvedMetadata) -> Map<String, Value> {
        let mut map: Map<String, Value> = self.props.clone().into_iter().collect();
        map.insert(
            "$exception_list".into(),
            serde_json::to_value(&self.exception_list).expect("exception list is serializable"),
        );
        map.insert(
            "$exception_sources".into(),
            serde_json::to_value(&metadata.sources).expect("exception sources are serializable"),
        );
        map.insert(
            "$exception_types".into(),
            serde_json::to_value(&metadata.types).expect("exception types are serializable"),
        );
        map.insert(
            "$exception_values".into(),
            serde_json::to_value(&metadata.messages).expect("exception messages are serializable"),
        );
        map.insert(
            "$exception_functions".into(),
            serde_json::to_value(&metadata.functions)
                .expect("exception functions are serializable"),
        );
        map.insert("$exception_handled".into(), Value::Bool(metadata.handled));
        if !metadata.releases.is_empty() {
            map.insert(
                "$exception_releases".into(),
                serde_json::to_value(&metadata.releases)
                    .expect("exception releases are serializable"),
            );
        }
        if let Some(name) = &self.proposed_issue_name {
            map.insert("$issue_name".into(), Value::String(name.clone()));
        }
        if let Some(description) = &self.proposed_issue_description {
            map.insert(
                "$issue_description".into(),
                Value::String(description.clone()),
            );
        }
        if !self.debug_images.is_empty() {
            map.insert(
                "$debug_images".into(),
                serde_json::to_value(&self.debug_images)
                    .expect("debug image properties are serializable"),
            );
        }
        map
    }

    fn properties_with_fingerprint(
        &self,
        metadata: &ResolvedMetadata,
        fingerprint: &FingerprintData,
        issue_id: Option<Uuid>,
    ) -> Value {
        let mut map = self.base_resolved_properties(metadata);
        map.insert(
            "$exception_fingerprint".into(),
            Value::String(fingerprint.value.clone()),
        );
        if let Some(version) = fingerprint.version {
            map.insert(
                "$exception_fingerprint_version".into(),
                serde_json::to_value(version).expect("fingerprint version is serializable"),
            );
        }
        map.insert(
            "$exception_fingerprint_record".into(),
            serde_json::to_value(&fingerprint.record).expect("fingerprint record is serializable"),
        );
        map.insert(
            "$exception_issue_id".into(),
            issue_id.map_or(Value::Null, |id| Value::String(id.to_string())),
        );
        Value::Object(map)
    }

    fn build_output(
        &self,
        metadata: &ResolvedMetadata,
        fingerprint: &FingerprintData,
        issue_id: Uuid,
    ) -> OutputErrProps {
        OutputErrProps {
            exception_list: self.exception_list.clone(),
            fingerprint: fingerprint.value.clone(),
            fingerprint_version: fingerprint.version,
            fingerprint_record: fingerprint.record.clone(),
            issue_id,
            other: self.props.clone(),
            handled: metadata.handled,
            releases: metadata.releases.clone(),
            types: metadata.types.clone(),
            values: metadata.messages.clone(),
            sources: metadata.sources.clone(),
            functions: metadata.functions.clone(),
        }
    }
}

impl TryFrom<AnyEvent> for ExceptionEvent<Parsed> {
    type Error = EventError;

    fn try_from(event: AnyEvent) -> Result<Self, Self::Error> {
        if event.event != "$exception" {
            return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
        }

        let mut properties = event.properties;
        if let Some(value) = properties
            .as_object_mut()
            .and_then(|object| object.get_mut("$exception_list"))
        {
            recursively_sanitize_properties(event.uuid, value, 0)?;
        }

        let mut raw: RawErrProps = serde_json::from_value(properties)
            .map_err(|error| EventError::InvalidProperties(event.uuid, error.to_string()))?;
        if raw.exception_list.is_empty() {
            return Err(EventError::EmptyExceptionList(event.uuid));
        }

        for exception in raw.exception_list.iter_mut() {
            if exception.exception_message.len() > MAX_EXCEPTION_VALUE_LENGTH {
                let truncate_at = exception
                    .exception_message
                    .char_indices()
                    .take_while(|(index, _)| *index < MAX_EXCEPTION_VALUE_LENGTH)
                    .last()
                    .map(|(index, character)| index + character.len_utf8())
                    .unwrap_or(0);
                exception.exception_message.truncate(truncate_at);
                exception.exception_message.push_str("...");
            }
            exception.exception_id = Some(Uuid::now_v7().to_string());
        }

        for key in [
            "$exception_sources",
            "$exception_types",
            "$exception_values",
            "$exception_functions",
            "$exception_releases",
            "$exception_fingerprint_version",
            "$exception_proposed_fingerprint",
            "$exception_fingerprint_record",
            "$exception_issue_id",
        ] {
            raw.other.remove(key);
        }

        let lib = raw.other.get("$lib").and_then(Value::as_str);
        let lib_version = raw.other.get("$lib_version").and_then(Value::as_str);
        let legacy_order_exception_list =
            normalize_wire_order(&mut raw.exception_list, lib, lib_version);

        Ok(ExceptionEvent {
            uuid: event.uuid,
            team_id: event.team_id,
            timestamp: event.timestamp,
            exception_list: raw.exception_list,
            debug_images: raw.debug_images,
            props: raw.other,
            proposed_issue_name: raw.issue_name,
            proposed_issue_description: raw.issue_description,
            state: Parsed {
                client_fingerprint: raw.fingerprint,
                legacy_order_exception_list,
                legacy_order_resolved: None,
            },
        })
    }
}

impl TryFrom<ClickHouseEvent> for ExceptionEvent<Parsed> {
    type Error = EventError;

    fn try_from(event: ClickHouseEvent) -> Result<Self, Self::Error> {
        AnyEvent::try_from(event)?.try_into()
    }
}

impl TryFrom<Result<ClickHouseEvent, EventError>> for ExceptionEvent<Parsed> {
    type Error = EventError;

    fn try_from(event: Result<ClickHouseEvent, EventError>) -> Result<Self, Self::Error> {
        event?.try_into()
    }
}
