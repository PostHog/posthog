use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use uuid::Uuid;

pub const MAX_EXCEPTION_VALUE_LENGTH: usize = 10_000;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case", tag = "type")]
pub enum FingerprintRecordPart {
    Frame {
        raw_id: String,
        pieces: Vec<String>,
    },
    Exception {
        id: Option<String>,
        pieces: Vec<String>,
    },
    Custom {
        rule_id: Uuid,
    },
    Manual,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ExceptionProperties {
    #[serde(
        rename = "$exception_list",
        default,
        skip_serializing_if = "Option::is_none"
    )]
    pub exception_list: Option<ExceptionList>,

    #[serde(
        rename = "$debug_images",
        default,
        skip_serializing_if = "Vec::is_empty"
    )]
    pub debug_images: Vec<Value>,

    #[serde(rename = "$exception_sources", skip_serializing_if = "Option::is_none")]
    pub exception_sources: Option<Vec<String>>,
    #[serde(rename = "$exception_types", skip_serializing_if = "Option::is_none")]
    pub exception_types: Option<Vec<String>>,
    #[serde(rename = "$exception_values", skip_serializing_if = "Option::is_none")]
    pub exception_messages: Option<Vec<String>>,
    #[serde(
        rename = "$exception_functions",
        skip_serializing_if = "Option::is_none"
    )]
    pub exception_functions: Option<Vec<String>>,
    #[serde(rename = "$exception_handled", skip_serializing_if = "Option::is_none")]
    pub exception_handled: Option<bool>,

    #[serde(
        rename = "$exception_releases",
        skip_serializing_if = "Map::is_empty",
        default
    )]
    pub exception_releases: Map<String, Value>,

    #[serde(
        rename = "$exception_fingerprint",
        skip_serializing_if = "Option::is_none"
    )]
    pub fingerprint: Option<String>,
    #[serde(
        rename = "$exception_proposed_fingerprint",
        skip_serializing_if = "Option::is_none"
    )]
    pub proposed_fingerprint: Option<String>,
    #[serde(
        rename = "$exception_fingerprint_record",
        skip_serializing_if = "Option::is_none"
    )]
    pub fingerprint_record: Option<Vec<FingerprintRecordPart>>,
    #[serde(
        rename = "$exception_issue_id",
        skip_serializing_if = "Option::is_none"
    )]
    pub issue_id: Option<Uuid>,
    #[serde(rename = "$issue_name", skip_serializing_if = "Option::is_none")]
    pub proposed_issue_name: Option<String>,
    #[serde(rename = "$issue_description", skip_serializing_if = "Option::is_none")]
    pub proposed_issue_description: Option<String>,

    #[serde(flatten)]
    pub props: Map<String, Value>,
}

impl ExceptionProperties {
    pub fn from_map(map: Map<String, Value>) -> Result<Self, serde_json::Error> {
        serde_json::from_value(Value::Object(map))
    }

    pub fn from_map_preserving_invalid_exception_fields(map: Map<String, Value>) -> Self {
        Self::from_map(map.clone()).unwrap_or_else(|_| Self {
            props: map,
            ..Self::default()
        })
    }

    pub fn to_map(&self) -> Result<Map<String, Value>, serde_json::Error> {
        Ok(serde_json::to_value(self)?
            .as_object()
            .cloned()
            .unwrap_or_default())
    }

    pub fn exception_list_is_empty(&self) -> bool {
        self.exception_list
            .as_ref()
            .map(ExceptionList::is_empty)
            .unwrap_or(true)
    }

    pub fn exception_list(&self) -> Option<&ExceptionList> {
        self.exception_list.as_ref()
    }

    pub fn normalize_for_ingestion(&mut self, event_id: &str) {
        let Some(exception_list) = self.exception_list.as_mut() else {
            return;
        };

        for (index, exception) in exception_list.0.iter_mut().enumerate() {
            truncate_exception_message(exception);
            ensure_exception_id(exception, event_id, index);
        }
    }
}

fn truncate_exception_message(exception: &mut Exception) {
    let Some(message) = exception.exception_message.as_mut() else {
        return;
    };
    if message.len() <= MAX_EXCEPTION_VALUE_LENGTH {
        return;
    }

    let truncate_at = message
        .char_indices()
        .take_while(|(index, _)| *index < MAX_EXCEPTION_VALUE_LENGTH)
        .last()
        .map(|(index, character)| index + character.len_utf8())
        .unwrap_or(0);
    message.truncate(truncate_at);
    message.push_str("...");
}

fn ensure_exception_id(exception: &mut Exception, event_id: &str, index: usize) {
    if has_exception_id(exception, "id") || has_exception_id(exception, "exception_id") {
        return;
    }

    exception.other.insert(
        "id".to_string(),
        Value::String(format!("{event_id}:{index}")),
    );
}

fn has_exception_id(exception: &Exception, key: &str) -> bool {
    exception
        .other
        .get(key)
        .and_then(Value::as_str)
        .is_some_and(|id| !id.is_empty())
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(transparent)]
pub struct ExceptionList(pub Vec<Exception>);

impl ExceptionList {
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn get_unique_messages(&self) -> Vec<String> {
        unique_by(
            self.0
                .iter()
                .filter_map(|exception| exception.exception_message.as_deref())
                .filter_map(non_empty_string),
        )
    }

    pub fn get_unique_types(&self) -> Vec<String> {
        unique_by(
            self.0
                .iter()
                .filter_map(|exception| exception.exception_type.as_deref())
                .filter_map(non_empty_string),
        )
    }

    pub fn get_unique_sources(&self) -> Vec<String> {
        unique_by(self.get_in_app_frames().filter_map(Frame::source_name))
    }

    pub fn get_unique_functions(&self) -> Vec<String> {
        unique_by(self.get_in_app_frames().filter_map(Frame::function_name))
    }

    pub fn get_release_map(&self) -> Map<String, Value> {
        Map::new()
    }

    pub fn get_is_handled(&self) -> bool {
        self.0
            .first()
            .and_then(|exception| exception.mechanism.as_ref())
            .and_then(|mechanism| mechanism.handled)
            .unwrap_or(false)
    }

    fn get_in_app_frames(&self) -> impl Iterator<Item = &Frame> {
        self.0
            .iter()
            .filter_map(|exception| exception.stacktrace.as_ref())
            .flat_map(Stacktrace::frames)
            .filter(|frame| frame.in_app())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Exception {
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    pub exception_type: Option<String>,
    #[serde(rename = "value", skip_serializing_if = "Option::is_none")]
    pub exception_message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mechanism: Option<Mechanism>,
    #[serde(rename = "stacktrace", skip_serializing_if = "Option::is_none")]
    pub stacktrace: Option<Stacktrace>,
    #[serde(flatten)]
    pub other: Map<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Mechanism {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub handled: Option<bool>,
    #[serde(flatten)]
    pub other: Map<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Stacktrace {
    #[serde(default)]
    pub frames: Vec<Frame>,
    #[serde(flatten)]
    pub other: Map<String, Value>,
}

impl Stacktrace {
    fn frames(&self) -> impl Iterator<Item = &Frame> {
        self.frames.iter()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RawErrProps {
    #[serde(rename = "$exception_list")]
    pub exception_list: ExceptionList,
    #[serde(
        rename = "$exception_fingerprint",
        skip_serializing_if = "Option::is_none"
    )]
    pub fingerprint: Option<String>,
    #[serde(rename = "$issue_name", skip_serializing_if = "Option::is_none")]
    pub issue_name: Option<String>,
    #[serde(rename = "$issue_description", skip_serializing_if = "Option::is_none")]
    pub issue_description: Option<String>,
    #[serde(rename = "$exception_handled", skip_serializing_if = "Option::is_none")]
    pub handled: Option<bool>,
    #[serde(
        rename = "$debug_images",
        default,
        skip_serializing_if = "Vec::is_empty"
    )]
    pub debug_images: Vec<Value>,
    #[serde(flatten)]
    pub other: Map<String, Value>,
}

#[derive(Debug, Default, Serialize, Deserialize, Clone, PartialEq)]
pub struct OutputErrProps {
    #[serde(rename = "$exception_list")]
    pub exception_list: ExceptionList,
    #[serde(rename = "$exception_fingerprint")]
    pub fingerprint: String,
    #[serde(rename = "$exception_proposed_fingerprint")]
    pub proposed_fingerprint: String,
    #[serde(rename = "$exception_fingerprint_record")]
    pub fingerprint_record: Vec<FingerprintRecordPart>,
    #[serde(rename = "$exception_issue_id")]
    pub issue_id: Uuid,
    #[serde(flatten)]
    pub other: Map<String, Value>,

    #[serde(rename = "$exception_handled")]
    pub handled: bool,
    #[serde(
        rename = "$exception_releases",
        skip_serializing_if = "Map::is_empty",
        default
    )]
    pub releases: Map<String, Value>,
    #[serde(rename = "$exception_types")]
    pub types: Vec<String>,
    #[serde(rename = "$exception_values")]
    pub values: Vec<String>,
    #[serde(rename = "$exception_sources")]
    pub sources: Vec<String>,
    #[serde(rename = "$exception_functions")]
    pub functions: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Frame {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filename: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolved_name: Option<String>,
    #[serde(rename = "function", skip_serializing_if = "Option::is_none")]
    pub function_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mangled_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub in_app: Option<bool>,
    #[serde(flatten)]
    pub other: Map<String, Value>,
}

impl Frame {
    fn source_name(&self) -> Option<&str> {
        self.source
            .as_deref()
            .or(self.filename.as_deref())
            .and_then(non_empty_string)
    }

    fn function_name(&self) -> Option<&str> {
        self.resolved_name
            .as_deref()
            .or(self.function_name.as_deref())
            .or(self.mangled_name.as_deref())
            .and_then(non_empty_string)
    }

    fn in_app(&self) -> bool {
        self.in_app.unwrap_or(true)
    }
}

fn unique_by<'a>(values: impl Iterator<Item = &'a str>) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut unique = Vec::new();
    for value in values {
        if seen.insert(value) {
            unique.push(value.to_string());
        }
    }
    unique
}

fn non_empty_string(value: &str) -> Option<&str> {
    if value.is_empty() {
        return None;
    }

    Some(value)
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn exception_list_collects_unique_values_from_in_app_frames() {
        let exception_list: ExceptionList = serde_json::from_value(json!([
            {
                "type": "TypeError",
                "value": "first boom",
                "mechanism": { "handled": true },
                "stacktrace": {
                    "frames": [
                        {
                            "filename": "app.js",
                            "function": "runExample"
                        },
                        {
                            "filename": "vendor.js",
                            "function": "vendorCall",
                            "in_app": false
                        }
                    ]
                }
            },
            {
                "type": "TypeError",
                "value": "second boom",
                "stacktrace": {
                    "frames": [
                        {
                            "source": "src/app.ts",
                            "resolved_name": "runExample"
                        }
                    ]
                }
            }
        ]))
        .unwrap();

        assert_eq!(exception_list.get_unique_types(), vec!["TypeError"]);
        assert_eq!(
            exception_list.get_unique_messages(),
            vec!["first boom", "second boom"]
        );
        assert_eq!(
            exception_list.get_unique_sources(),
            vec!["app.js", "src/app.ts"]
        );
        assert_eq!(exception_list.get_unique_functions(), vec!["runExample"]);
        assert!(exception_list.get_is_handled());
    }

    #[test]
    fn normalize_for_ingestion_adds_exception_ids_and_truncates_long_values() {
        let long_value = "x".repeat(MAX_EXCEPTION_VALUE_LENGTH + 10);
        let mut properties = ExceptionProperties::from_map(
            json!({
                "$exception_list": [
                    { "type": "Error", "value": long_value },
                    { "type": "Error", "value": "kept", "id": "existing" },
                    { "type": "Error", "value": "null id", "id": null }
                ]
            })
            .as_object()
            .unwrap()
            .clone(),
        )
        .unwrap();

        properties.normalize_for_ingestion("event-1");

        let exceptions = &properties.exception_list.unwrap().0;
        assert_eq!(exceptions[0].other.get("id"), Some(&json!("event-1:0")));
        assert_eq!(exceptions[1].other.get("id"), Some(&json!("existing")));
        assert_eq!(exceptions[2].other.get("id"), Some(&json!("event-1:2")));
        assert_eq!(
            exceptions[0].exception_message.as_ref().unwrap().len(),
            MAX_EXCEPTION_VALUE_LENGTH + 3
        );
        assert!(exceptions[0]
            .exception_message
            .as_ref()
            .unwrap()
            .ends_with("..."));
    }
}
