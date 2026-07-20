use std::collections::HashMap;

use common_types::ClickHouseEvent;
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::{
    error::EventError,
    fingerprinting::{Fingerprint, FingerprintRecordPart, FingerprintVersion},
    frames::releases::ReleaseInfo,
    issue_resolution::Issue,
    langs::native::DebugImage,
    modes::processing::normalization::normalize_wire_order,
    recursively_sanitize_properties,
    types::{event::AnyEvent, ExceptionList, ProcessedExceptionProperties, RawExceptionProperties},
};

use super::ProcessedExceptionPropertiesWire;

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
pub struct SelectedFingerprint {
    value: String,
    version: Option<FingerprintVersion>,
    record: Vec<FingerprintRecordPart>,
}

impl SelectedFingerprint {
    pub(crate) fn manual(value: String) -> Self {
        Self {
            value,
            version: None,
            record: vec![FingerprintRecordPart::Manual],
        }
    }

    pub(crate) fn custom(rule_id: Uuid) -> Self {
        Self {
            value: format!("custom-rule:{rule_id}"),
            version: None,
            record: vec![FingerprintRecordPart::Custom { rule_id }],
        }
    }

    pub(crate) fn automatic(version: FingerprintVersion, fingerprint: Fingerprint) -> Self {
        Self {
            value: fingerprint.value,
            version: Some(version),
            record: fingerprint.record,
        }
    }

    pub fn value(&self) -> &str {
        &self.value
    }

    pub fn version(&self) -> Option<FingerprintVersion> {
        self.version
    }

    pub fn record(&self) -> &[FingerprintRecordPart] {
        &self.record
    }
}

#[derive(Debug, Clone)]
pub struct Fingerprinted {
    pub(crate) metadata: ResolvedMetadata,
    pub(crate) fingerprint: SelectedFingerprint,
}

#[derive(Debug, Clone)]
pub struct Linked {
    pub(crate) metadata: ResolvedMetadata,
    pub(crate) fingerprint: SelectedFingerprint,
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

/// Internal typestate carrier for a successfully accepted exception event.
///
/// The state parameter proves which processing stages have completed. This
/// carrier intentionally has no serde implementation: wire payloads cannot
/// prove that resolution, grouping, linking, rate checking, or alerting ran.
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
        fingerprint: SelectedFingerprint,
    ) -> ExceptionEvent<Fingerprinted> {
        self.map_state(|state| Fingerprinted {
            metadata: state.metadata,
            fingerprint,
        })
    }

    pub fn grouping_rule_properties(&self) -> Value {
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
    pub fn fingerprint(&self) -> &SelectedFingerprint {
        &self.state.fingerprint
    }

    pub(crate) fn into_linked(self, issue: Issue) -> ExceptionEvent<Linked> {
        self.map_state(|state| Linked {
            metadata: state.metadata,
            fingerprint: state.fingerprint,
            issue,
        })
    }

    pub fn suppression_rule_properties(&self) -> Value {
        self.properties_with_fingerprint(&self.state.metadata, &self.state.fingerprint, None)
    }

    pub fn processed_properties(&self, issue: &Issue) -> ProcessedExceptionProperties {
        self.build_processed_properties(&self.state.metadata, &self.state.fingerprint, issue.id)
    }
}

impl ExceptionEvent<Linked> {
    pub fn issue(&self) -> &Issue {
        &self.state.issue
    }

    pub fn issue_id(&self) -> Uuid {
        self.state.issue.id
    }

    pub fn rate_limit_rule_properties(&self) -> Value {
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
    pub fn issue(&self) -> &Issue {
        &self.state.linked.issue
    }

    pub fn processed_properties(&self) -> ProcessedExceptionProperties {
        self.build_processed_properties(
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
    pub fn into_clickhouse_properties(self) -> Value {
        let ExceptionEvent {
            exception_list,
            debug_images,
            props,
            proposed_issue_name,
            proposed_issue_description,
            state,
            ..
        } = self;
        let Linked {
            metadata,
            fingerprint,
            issue,
        } = state.linked;

        let mut map: Map<String, Value> = props.into_iter().collect();
        map.insert(
            "$exception_list".into(),
            serde_json::to_value(exception_list).expect("exception list is serializable"),
        );
        map.insert(
            "$exception_sources".into(),
            serde_json::to_value(metadata.sources).expect("exception sources are serializable"),
        );
        map.insert(
            "$exception_types".into(),
            serde_json::to_value(metadata.types).expect("exception types are serializable"),
        );
        map.insert(
            "$exception_values".into(),
            serde_json::to_value(metadata.messages).expect("exception messages are serializable"),
        );
        map.insert(
            "$exception_functions".into(),
            serde_json::to_value(metadata.functions).expect("exception functions are serializable"),
        );
        map.insert("$exception_handled".into(), Value::Bool(metadata.handled));
        if !metadata.releases.is_empty() {
            map.insert(
                "$exception_releases".into(),
                serde_json::to_value(metadata.releases)
                    .expect("exception releases are serializable"),
            );
        }
        map.insert(
            "$exception_fingerprint".into(),
            Value::String(fingerprint.value),
        );
        if let Some(version) = fingerprint.version {
            map.insert(
                "$exception_fingerprint_version".into(),
                serde_json::to_value(version).expect("fingerprint version is serializable"),
            );
        }
        map.insert(
            "$exception_fingerprint_record".into(),
            serde_json::to_value(fingerprint.record).expect("fingerprint record is serializable"),
        );
        map.insert(
            "$exception_issue_id".into(),
            Value::String(issue.id.to_string()),
        );
        if let Some(name) = proposed_issue_name {
            map.insert("$issue_name".into(), Value::String(name));
        }
        if let Some(description) = proposed_issue_description {
            map.insert("$issue_description".into(), Value::String(description));
        }
        if !debug_images.is_empty() {
            map.insert(
                "$debug_images".into(),
                serde_json::to_value(debug_images)
                    .expect("debug image properties are serializable"),
            );
        }
        Value::Object(map)
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
        fingerprint: &SelectedFingerprint,
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

    fn build_processed_properties(
        &self,
        metadata: &ResolvedMetadata,
        fingerprint: &SelectedFingerprint,
        issue_id: Uuid,
    ) -> ProcessedExceptionProperties {
        ProcessedExceptionProperties(ProcessedExceptionPropertiesWire {
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
        })
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

        let mut raw: RawExceptionProperties = serde_json::from_value(properties)
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

#[cfg(test)]
mod tests {
    use super::*;

    fn resolved_event() -> ExceptionEvent<Resolved> {
        ExceptionEvent {
            uuid: Uuid::now_v7(),
            team_id: 42,
            timestamp: "2026-01-01T00:00:00Z".to_string(),
            exception_list: ExceptionList(vec![crate::types::Exception {
                exception_id: Some("exception-id".to_string()),
                exception_type: "Error".to_string(),
                exception_message: "boom".to_string(),
                mechanism: None,
                module: None,
                thread_id: None,
                stack: None,
            }]),
            debug_images: vec![],
            props: HashMap::from([("passthrough".to_string(), Value::Bool(true))]),
            proposed_issue_name: None,
            proposed_issue_description: None,
            state: Resolved {
                metadata: ResolvedMetadata {
                    sources: vec![],
                    types: vec!["Error".to_string()],
                    messages: vec!["boom".to_string()],
                    functions: vec![],
                    handled: false,
                    releases: HashMap::new(),
                },
                client_fingerprint: Some("client-fingerprint".to_string()),
                legacy_order_resolved: None,
            },
        }
    }

    #[test]
    fn selected_fingerprint_constructors_keep_origin_coherent() {
        let manual = SelectedFingerprint::manual("manual-value".to_string());
        assert_eq!(manual.value(), "manual-value");
        assert_eq!(manual.version(), None);
        assert!(matches!(manual.record(), [FingerprintRecordPart::Manual]));

        let rule_id = Uuid::now_v7();
        let custom = SelectedFingerprint::custom(rule_id);
        assert_eq!(custom.value(), format!("custom-rule:{rule_id}"));
        assert_eq!(custom.version(), None);
        assert!(matches!(
            custom.record(),
            [FingerprintRecordPart::Custom { rule_id: id }] if *id == rule_id
        ));

        let automatic = SelectedFingerprint::automatic(
            FingerprintVersion::V2,
            Fingerprint {
                value: "automatic-value".to_string(),
                record: vec![FingerprintRecordPart::Exception {
                    id: None,
                    pieces: vec!["Error".to_string()],
                }],
            },
        );
        assert_eq!(automatic.value(), "automatic-value");
        assert_eq!(automatic.version(), Some(FingerprintVersion::V2));
        assert!(matches!(
            automatic.record(),
            [FingerprintRecordPart::Exception { .. }]
        ));
    }

    #[test]
    fn purpose_specific_projections_preserve_issue_id_nullability() {
        let resolved = resolved_event();
        let grouping = resolved.grouping_rule_properties();
        assert_eq!(grouping["$exception_fingerprint"], "client-fingerprint");
        assert!(grouping["$exception_fingerprint_record"].is_null());
        assert!(grouping["$exception_issue_id"].is_null());

        let fingerprinted = resolved.into_fingerprinted(SelectedFingerprint::manual(
            "client-fingerprint".to_string(),
        ));
        let suppression = fingerprinted.suppression_rule_properties();
        assert_eq!(suppression["$exception_fingerprint"], "client-fingerprint");
        assert_eq!(
            suppression["$exception_fingerprint_record"],
            serde_json::json!([{"type": "manual"}])
        );
        assert!(suppression["$exception_issue_id"].is_null());

        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 42,
            status: crate::issue_resolution::IssueStatus::Active,
            name: None,
            description: None,
            created_at: chrono::Utc::now(),
        };
        let assignment = serde_json::to_value(fingerprinted.processed_properties(&issue)).unwrap();
        assert_eq!(assignment["$exception_issue_id"], issue.id.to_string());
        assert_eq!(assignment["passthrough"], true);

        let linked = fingerprinted.into_linked(issue.clone());
        let rate_limit = linked.rate_limit_rule_properties();
        assert_eq!(rate_limit["$exception_issue_id"], issue.id.to_string());
        assert_eq!(rate_limit["passthrough"], true);
    }
}
