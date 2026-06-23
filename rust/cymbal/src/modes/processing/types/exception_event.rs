//! Typestate model of an exception event as it moves through the processing
//! pipeline. A single [`ExceptionEvent<S>`] envelope carries the data present at
//! every stage; the stage marker `S` (`Raw` → `Fingerprinted` → `Linked`)
//! carries only what that stage produced, so the compiler enforces ordering —
//! e.g. an `issue_id` simply does not exist before linking.
//!
//! Frame resolution is tracked inside `exception_list` via
//! [`Stacktrace::Raw`]/[`Stacktrace::Resolved`], so it is not a separate
//! event-level stage.

use std::collections::HashMap;

use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::core::sanitize::recursively_sanitize_properties;
use crate::error::EventError;
use crate::fingerprinting::{Fingerprint, FingerprintRecordPart};
use crate::issue_resolution::Issue;
use crate::langs::native::DebugImage;

use super::event::AnyEvent;
use super::exception_properties::MAX_EXCEPTION_VALUE_LENGTH;
use super::{ExceptionList, OutputErrProps, RawErrProps};

/// Not-yet-fingerprinted event, straight off ingestion.
#[derive(Debug, Clone)]
pub struct Raw {
    /// A fingerprint the client sent, if any. Honored over the computed one.
    pub client_fingerprint: Option<String>,
}

/// Fingerprinted but not yet linked to an issue.
#[derive(Debug, Clone)]
pub struct Fingerprinted {
    pub fingerprint: String,
    pub proposed_fingerprint: String,
    pub record: Vec<FingerprintRecordPart>,
}

/// Linked to an issue — the terminal, emittable state.
#[derive(Debug, Clone)]
pub struct Linked {
    pub fingerprint: String,
    pub proposed_fingerprint: String,
    pub record: Vec<FingerprintRecordPart>,
    pub issue_id: Uuid,
    pub issue: Issue,
}

/// An exception event parameterized by pipeline stage `S`. The fields here exist
/// at every stage and are declared once; stage-specific data lives in `stage`.
#[derive(Debug, Clone)]
pub struct ExceptionEvent<S> {
    // Ingestion identity — never part of the serialized `$exception_*` props.
    pub uuid: Uuid,
    pub team_id: i32,
    pub timestamp: String,

    // Domain payload, present from parse onward.
    pub exception_list: ExceptionList,
    pub handled: Option<bool>,
    pub debug_images: Vec<DebugImage>,
    pub other: HashMap<String, Value>,

    // Client-supplied proposals, used at issue create/link time.
    pub proposed_issue_name: Option<String>,
    pub proposed_issue_description: Option<String>,

    // Stage-specific data — and only this changes between stages.
    pub stage: S,
}

impl<S> ExceptionEvent<S> {
    /// Move the shared envelope into a new stage. Declared once.
    fn map_stage<T>(self, stage: T) -> ExceptionEvent<T> {
        ExceptionEvent {
            uuid: self.uuid,
            team_id: self.team_id,
            timestamp: self.timestamp,
            exception_list: self.exception_list,
            handled: self.handled,
            debug_images: self.debug_images,
            other: self.other,
            proposed_issue_name: self.proposed_issue_name,
            proposed_issue_description: self.proposed_issue_description,
            stage,
        }
    }

    /// Append a processing error message to the passthrough `$cymbal_errors` array.
    pub fn add_error_message(&mut self, msg: impl ToString) {
        let mut errors = match self.other.remove("$cymbal_errors") {
            Some(Value::Array(errors)) => errors,
            _ => Vec::new(),
        };
        errors.push(Value::String(msg.to_string()));
        self.other
            .insert("$cymbal_errors".to_string(), Value::Array(errors));
    }
}

impl ExceptionEvent<Raw> {
    /// Apply the computed fingerprint, honoring a client-sent override. Mirrors
    /// the legacy `RawErrProps::to_fingerprinted` override rules.
    pub fn into_fingerprinted(self, computed: Fingerprint) -> ExceptionEvent<Fingerprinted> {
        let proposed_fingerprint = computed.value.clone();
        let (fingerprint, record) = match &self.stage.client_fingerprint {
            Some(client) => {
                let value = if client.len() > 64 {
                    use sha2::{Digest, Sha512};
                    let mut hasher = Sha512::default();
                    hasher.update(client);
                    format!("{:x}", hasher.finalize())
                } else {
                    client.clone()
                };
                (value, vec![FingerprintRecordPart::Manual])
            }
            None => (computed.value, computed.record),
        };
        let stage = Fingerprinted {
            fingerprint,
            proposed_fingerprint,
            record,
        };
        self.map_stage(stage)
    }
}

impl ExceptionEvent<Fingerprinted> {
    /// Link to an issue — the only transition that yields an emittable event.
    pub fn into_linked(self, issue: Issue) -> ExceptionEvent<Linked> {
        let issue_id = issue.id;
        let stage = Linked {
            fingerprint: self.stage.fingerprint.clone(),
            proposed_fingerprint: self.stage.proposed_fingerprint.clone(),
            record: self.stage.record.clone(),
            issue_id,
            issue,
        };
        self.map_stage(stage)
    }
}

impl<S> ExceptionEvent<S> {
    /// Build the internal-events wire shape (`OutputErrProps`) from the envelope
    /// plus the fingerprint/issue data the caller has in hand. The materialized
    /// search arrays are derived from `exception_list` here rather than stored.
    fn build_output(
        &self,
        fingerprint: String,
        proposed_fingerprint: String,
        record: Vec<FingerprintRecordPart>,
        issue_id: Uuid,
    ) -> OutputErrProps {
        OutputErrProps {
            exception_list: self.exception_list.clone(),
            fingerprint,
            proposed_fingerprint,
            fingerprint_record: record,
            issue_id,
            other: self.other.clone(),
            handled: self
                .handled
                .unwrap_or_else(|| self.exception_list.get_is_handled()),
            releases: self.exception_list.get_release_map(),
            types: self.exception_list.get_unique_types(),
            values: self.exception_list.get_unique_messages(),
            sources: self.exception_list.get_unique_sources(),
            functions: self.exception_list.get_unique_functions(),
        }
    }
}

impl ExceptionEvent<Raw> {
    /// Properties object used to evaluate grouping rules — the resolved event
    /// properties as a rule would see them (derived arrays included). Mirrors
    /// what the legacy pipeline fed grouping after `PropertiesResolver` ran.
    pub fn to_grouping_value(&self) -> Value {
        let mut map = Map::new();
        for (k, v) in &self.other {
            map.insert(k.clone(), v.clone());
        }
        map.insert(
            "$exception_list".into(),
            serde_json::to_value(&self.exception_list).unwrap_or(Value::Null),
        );
        map.insert(
            "$exception_types".into(),
            json!(self.exception_list.get_unique_types()),
        );
        map.insert(
            "$exception_values".into(),
            json!(self.exception_list.get_unique_messages()),
        );
        map.insert(
            "$exception_sources".into(),
            json!(self.exception_list.get_unique_sources()),
        );
        map.insert(
            "$exception_functions".into(),
            json!(self.exception_list.get_unique_functions()),
        );
        map.insert(
            "$exception_handled".into(),
            json!(self
                .handled
                .unwrap_or_else(|| self.exception_list.get_is_handled())),
        );
        let releases = self.exception_list.get_release_map();
        if !releases.is_empty() {
            map.insert(
                "$exception_releases".into(),
                serde_json::to_value(releases).unwrap_or(Value::Null),
            );
        }
        if let Some(fp) = &self.stage.client_fingerprint {
            map.insert("$exception_fingerprint".into(), json!(fp));
        }
        if let Some(n) = &self.proposed_issue_name {
            map.insert("$issue_name".into(), json!(n));
        }
        if let Some(d) = &self.proposed_issue_description {
            map.insert("$issue_description".into(), json!(d));
        }
        if !self.debug_images.is_empty() {
            map.insert(
                "$debug_images".into(),
                serde_json::to_value(&self.debug_images).unwrap_or(Value::Null),
            );
        }
        Value::Object(map)
    }
}

impl ExceptionEvent<Fingerprinted> {
    /// Project to the internal-events wire shape, given the issue this event is
    /// being linked to. Used during linking before the `Linked` transition.
    pub fn to_output(&self, issue_id: Uuid) -> OutputErrProps {
        self.build_output(
            self.stage.fingerprint.clone(),
            self.stage.proposed_fingerprint.clone(),
            self.stage.record.clone(),
            issue_id,
        )
    }
}

impl ExceptionEvent<Linked> {
    /// Project to the internal-events wire shape (`OutputErrProps`).
    pub fn to_output(&self) -> OutputErrProps {
        self.build_output(
            self.stage.fingerprint.clone(),
            self.stage.proposed_fingerprint.clone(),
            self.stage.record.clone(),
            self.stage.issue_id,
        )
    }

    /// Project to the ClickHouse-bound event-properties shape. This is the
    /// internal-events shape plus the client-facing `$issue_name`,
    /// `$issue_description`, and `$debug_images` that the pipeline preserves.
    pub fn to_clickhouse_value(&self) -> Value {
        let mut value = serde_json::to_value(self.to_output()).unwrap_or(Value::Null);
        if let Value::Object(map) = &mut value {
            if let Some(name) = &self.proposed_issue_name {
                map.insert("$issue_name".into(), json!(name));
            }
            if let Some(description) = &self.proposed_issue_description {
                map.insert("$issue_description".into(), json!(description));
            }
            if !self.debug_images.is_empty() {
                map.insert(
                    "$debug_images".into(),
                    serde_json::to_value(&self.debug_images).unwrap_or(Value::Null),
                );
            }
        }
        value
    }
}

impl TryFrom<AnyEvent> for ExceptionEvent<Raw> {
    type Error = EventError;

    fn try_from(event: AnyEvent) -> Result<Self, Self::Error> {
        if event.event != "$exception" {
            return Err(EventError::WrongEventType(event.event.clone(), event.uuid));
        }

        let mut properties: Value = serde_json::from_value(event.properties)
            .map_err(|e| EventError::InvalidProperties(event.uuid, e.to_string()))?;

        if let Some(v) = properties
            .as_object_mut()
            .and_then(|o| o.get_mut("$exception_list"))
        {
            // The strings in the exception list can end up in PG arbitrarily.
            recursively_sanitize_properties(event.uuid, v, 0)?;
        }

        let raw: RawErrProps = serde_json::from_value(properties)
            .map_err(|e| EventError::InvalidProperties(event.uuid, e.to_string()))?;

        let mut exception_list = raw.exception_list;
        if exception_list.is_empty() {
            return Err(EventError::EmptyExceptionList(event.uuid));
        }

        for exception in exception_list.iter_mut() {
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

        Ok(ExceptionEvent {
            uuid: event.uuid,
            team_id: event.team_id,
            timestamp: event.timestamp,
            exception_list,
            handled: raw.handled,
            debug_images: raw.debug_images,
            other: raw.other,
            proposed_issue_name: raw.issue_name,
            proposed_issue_description: raw.issue_description,
            stage: Raw {
                client_fingerprint: raw.fingerprint,
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::issue_resolution::IssueStatus;
    use chrono::Utc;
    use serde_json::json;

    fn raw_event() -> ExceptionEvent<Raw> {
        let any = AnyEvent {
            uuid: Uuid::now_v7(),
            event: "$exception".to_string(),
            team_id: 1,
            timestamp: "2021-01-01T00:00:00Z".to_string(),
            properties: json!({
                "$exception_list": [{ "type": "TypeError", "value": "boom" }],
                "$exception_fingerprint": "client-fp",
                "custom_prop": "kept",
            }),
            others: HashMap::new(),
        };
        ExceptionEvent::<Raw>::try_from(any).unwrap()
    }

    #[test]
    fn parses_raw_event_preserving_passthrough_and_client_fingerprint() {
        let raw = raw_event();
        assert_eq!(raw.exception_list.len(), 1);
        assert_eq!(raw.exception_list[0].exception_type, "TypeError");
        assert_eq!(raw.stage.client_fingerprint.as_deref(), Some("client-fp"));
        assert_eq!(raw.other.get("custom_prop").unwrap(), "kept");
        // exception_id is assigned during parse
        assert!(raw.exception_list[0].exception_id.is_some());
    }

    #[test]
    fn client_fingerprint_wins_over_computed() {
        let raw = raw_event();
        let computed = Fingerprint {
            value: "computed".to_string(),
            record: vec![],
            assignment: None,
        };
        let fp = raw.into_fingerprinted(computed);
        assert_eq!(fp.stage.fingerprint, "client-fp");
        assert_eq!(fp.stage.proposed_fingerprint, "computed");
        assert!(matches!(
            fp.stage.record.as_slice(),
            [FingerprintRecordPart::Manual]
        ));
    }

    #[test]
    fn linked_projects_to_output_with_derived_arrays() {
        let raw = raw_event();
        let computed = Fingerprint {
            value: "computed".to_string(),
            record: vec![],
            assignment: None,
        };
        // Drop the client fingerprint so the computed one is used.
        let mut fp = raw.into_fingerprinted(computed);
        fp.stage.fingerprint = "computed".to_string();

        let issue = Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status: IssueStatus::Active,
            name: None,
            description: None,
            created_at: Utc::now(),
        };
        let issue_id = issue.id;
        let linked = fp.into_linked(issue);

        let output = linked.to_output();
        assert_eq!(output.issue_id, issue_id);
        assert_eq!(output.fingerprint, "computed");
        assert_eq!(output.types, vec!["TypeError".to_string()]);
        assert_eq!(output.values, vec!["boom".to_string()]);
        assert_eq!(output.other.get("custom_prop").unwrap(), "kept");
    }
}
