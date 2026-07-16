use common_types::error_tracking::RawFrameId;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::hash::Hash;
use std::ops::{Deref, DerefMut};
use uuid::Uuid;

use crate::fingerprinting::{FingerprintRecordPart, FingerprintVersion};
use crate::frames::releases::{ReleaseInfo, ReleaseRecord};
use crate::frames::{Frame, RawFrame};
use crate::langs::native::DebugImage;
use crate::metric_consts::POSTHOG_SDK_EXCEPTION_RESOLVED;

pub mod batch;
pub mod event;
pub mod exception_event;
pub mod operator;
pub mod stage;

// Shared exception/stacktrace types live in core; re-exported here so the
// processing event model can keep referring to `crate::types::*`.
pub use crate::core::types::{Exception, Mechanism, Stacktrace};

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ExceptionList(pub Vec<Exception>);

impl From<Vec<Exception>> for ExceptionList {
    fn from(exceptions: Vec<Exception>) -> Self {
        ExceptionList(exceptions)
    }
}

impl From<&[Exception]> for ExceptionList {
    fn from(exceptions: &[Exception]) -> Self {
        ExceptionList(exceptions.to_vec())
    }
}

impl Deref for ExceptionList {
    type Target = Vec<Exception>;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl DerefMut for ExceptionList {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

impl IntoIterator for ExceptionList {
    type Item = Exception;
    type IntoIter = std::vec::IntoIter<Self::Item>;

    fn into_iter(self) -> Self::IntoIter {
        self.0.into_iter()
    }
}

impl ExceptionList {
    fn get_frames_iter(&self) -> impl Iterator<Item = &Frame> {
        self.iter()
            .filter_map(|e| e.stack.as_ref())
            .flat_map(Stacktrace::get_frames)
    }

    fn get_in_app_frames(&self) -> impl Iterator<Item = &Frame> {
        self.get_frames_iter().filter(|f| f.in_app)
    }

    pub fn get_unique_messages(&self) -> Vec<String> {
        unique_by(self.iter(), |e| Some(e.exception_message.clone()))
    }

    pub fn get_unique_types(&self) -> Vec<String> {
        unique_by(self.iter(), |e| Some(e.exception_type.clone()))
    }

    pub fn get_unique_sources(&self) -> Vec<String> {
        unique_by(self.get_in_app_frames(), |f| f.source.clone())
    }

    pub fn get_unique_functions(&self) -> Vec<String> {
        unique_by(self.get_in_app_frames(), |f| f.resolved_name.clone())
    }

    pub fn get_release_map(&self) -> HashMap<String, ReleaseInfo> {
        ReleaseRecord::collect_to_map(self.get_frames_iter().filter_map(|f| f.release.as_ref()))
    }

    pub fn get_is_handled(&self) -> bool {
        self.first()
            .and_then(|e| e.mechanism.as_ref())
            .and_then(|m| m.handled)
            .unwrap_or(false)
    }
}

/// Untrusted exception properties accepted from ClickHouse and SDK event payloads.
///
/// Deserialization checks only the wire shape. Sanitization, non-empty list
/// validation, normalization, and construction of `ExceptionEvent<Parsed>`
/// happen at the event conversion boundary.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct RawExceptionProperties {
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
    pub debug_images: Vec<DebugImage>,
    /// Properties not interpreted by Cymbal, preserved across processing.
    #[serde(flatten)]
    pub other: HashMap<String, Value>,
}

/// The stable JSON representation of exception properties after Cymbal processing.
///
/// The public wrapper prevents ordinary callers from defaulting or independently
/// assembling successful pipeline products. This private DTO remains the single
/// source of truth for the external property names and omission behavior.
#[derive(Debug, Serialize, Deserialize, Clone)]
struct ProcessedExceptionPropertiesWire {
    #[serde(rename = "$exception_list")]
    exception_list: ExceptionList,
    #[serde(rename = "$exception_fingerprint")]
    fingerprint: String,
    #[serde(
        rename = "$exception_fingerprint_version",
        skip_serializing_if = "Option::is_none"
    )]
    fingerprint_version: Option<FingerprintVersion>,
    #[serde(rename = "$exception_fingerprint_record")]
    fingerprint_record: Vec<FingerprintRecordPart>,
    #[serde(rename = "$exception_issue_id")]
    issue_id: Uuid,
    #[serde(flatten)]
    other: HashMap<String, Value>,
    #[serde(rename = "$exception_handled")]
    handled: bool,
    #[serde(
        rename = "$exception_releases",
        skip_serializing_if = "HashMap::is_empty",
        default
    )]
    releases: HashMap<String, ReleaseInfo>,
    #[serde(rename = "$exception_types")]
    types: Vec<String>,
    #[serde(rename = "$exception_values")]
    values: Vec<String>,
    #[serde(rename = "$exception_sources")]
    sources: Vec<String>,
    #[serde(rename = "$exception_functions")]
    functions: Vec<String>,
}

/// Validated processed exception properties used at serialization boundaries.
///
/// This is a boundary value, not a pipeline state. Deserializing it does not
/// construct or imply an `ExceptionEvent<S>` processing state.
#[derive(Debug, Serialize, Clone)]
#[serde(transparent)]
pub struct ProcessedExceptionProperties(ProcessedExceptionPropertiesWire);

impl<'de> Deserialize<'de> for ProcessedExceptionProperties {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let wire = ProcessedExceptionPropertiesWire::deserialize(deserializer)?;
        if wire.exception_list.is_empty() {
            return Err(serde::de::Error::custom(
                "processed exception list must not be empty",
            ));
        }
        Ok(Self(wire))
    }
}

impl ProcessedExceptionProperties {
    pub fn exception_list(&self) -> &ExceptionList {
        &self.0.exception_list
    }

    pub fn fingerprint(&self) -> &str {
        &self.0.fingerprint
    }

    pub fn fingerprint_version(&self) -> Option<FingerprintVersion> {
        self.0.fingerprint_version
    }

    pub fn fingerprint_record(&self) -> &[FingerprintRecordPart] {
        &self.0.fingerprint_record
    }

    pub fn issue_id(&self) -> Uuid {
        self.0.issue_id
    }

    pub fn properties(&self) -> &HashMap<String, Value> {
        &self.0.other
    }

    pub fn is_handled(&self) -> bool {
        self.0.handled
    }

    pub fn releases(&self) -> &HashMap<String, ReleaseInfo> {
        &self.0.releases
    }

    pub fn types(&self) -> &[String] {
        &self.0.types
    }

    pub fn values(&self) -> &[String] {
        &self.0.values
    }

    pub fn sources(&self) -> &[String] {
        &self.0.sources
    }

    pub fn functions(&self) -> &[String] {
        &self.0.functions
    }
}

// Deduplicates while preserving first-seen order, so derived properties
// ($exception_types, $exception_values, ...) follow the $exception_list order.
fn unique_by<T, I, F, K>(items: I, key_extractor: F) -> Vec<K>
where
    I: Iterator<Item = T>,
    F: Fn(T) -> Option<K>,
    K: Eq + Hash + Clone,
{
    let mut seen = HashSet::new();
    items
        .filter_map(key_extractor)
        .filter(|key| seen.insert(key.clone()))
        .collect()
}

impl Stacktrace {
    pub fn resolve(
        &self,
        team_id: i32,
        lookup_table: &HashMap<RawFrameId, Vec<Frame>>,
        debug_images: &[DebugImage],
    ) -> Option<Self> {
        let Stacktrace::Raw { frames: raw_frames } = self else {
            return Some(self.clone());
        };

        let mut resolved_frames = Vec::with_capacity(raw_frames.len() + 10);
        for raw_frame in raw_frames {
            match lookup_table.get(&raw_frame.raw_id(team_id, debug_images)) {
                Some(resolved) => resolved_frames.extend(resolved.clone()),
                None => return None,
            }
        }

        metrics::counter!(POSTHOG_SDK_EXCEPTION_RESOLVED)
            .increment(resolved_frames.iter().filter(|f| f.suspicious).count() as u64);

        Some(Stacktrace::Resolved {
            frames: resolved_frames,
        })
    }

    pub fn get_raw_frames(&self) -> &[RawFrame] {
        match self {
            Stacktrace::Raw { frames } => frames,
            _ => &[],
        }
    }

    pub fn get_frames(&self) -> &[Frame] {
        match self {
            Stacktrace::Resolved { frames } => frames,
            _ => &[],
        }
    }
}

#[cfg(test)]
mod test {
    use common_types::ClickHouseEvent;
    use serde_json::{json, Error, Value};
    use uuid::Uuid;

    use crate::{frames::RawFrame, types::Stacktrace};

    use super::{Exception, ExceptionList, ProcessedExceptionProperties, RawExceptionProperties};

    #[test]
    fn it_deserialises_error_props() {
        let raw: &'static str = include_str!("../../../../tests/static/raw_ch_exception_list.json");

        let raw: ClickHouseEvent = serde_json::from_str(raw).unwrap();

        let props: RawExceptionProperties = serde_json::from_str(&raw.properties.unwrap()).unwrap();
        let exception_list = &props.exception_list;

        assert_eq!(exception_list.len(), 1);
        assert_eq!(
            exception_list[0].exception_type,
            "UnhandledRejection".to_string()
        );
        assert_eq!(exception_list[0].exception_message, "Unexpected usage");
        let mechanism = exception_list[0].mechanism.as_ref().unwrap();
        assert_eq!(mechanism.handled, Some(false));
        assert_eq!(mechanism.mechanism_type, None);
        assert_eq!(mechanism.source, None);
        assert_eq!(mechanism.synthetic, Some(false));

        let Stacktrace::Raw { frames } = exception_list[0].stack.as_ref().unwrap() else {
            panic!("Expected a Raw stacktrace")
        };
        assert_eq!(frames.len(), 2);
        let RawFrame::JavaScriptWeb(frame) = &frames[0] else {
            panic!("Expected a JavaScript frame")
        };

        assert_eq!(
            frame.source_url,
            Some("https://app-static.eu.posthog.com/static/chunk-PGUQKT6S.js".to_string())
        );
        assert_eq!(frame.fn_name, "?".to_string());
        assert!(frame.meta.in_app);
        assert_eq!(frame.location.as_ref().unwrap().line, 64);
        assert_eq!(frame.location.as_ref().unwrap().column, 25112);

        let RawFrame::JavaScriptWeb(frame) = &frames[1] else {
            panic!("Expected a JavaScript frame")
        };
        assert_eq!(
            frame.source_url,
            Some("https://app-static.eu.posthog.com/static/chunk-PGUQKT6S.js".to_string())
        );
        assert_eq!(frame.fn_name, "n.loadForeignModule".to_string());
        assert!(frame.meta.in_app);
        assert_eq!(frame.location.as_ref().unwrap().line, 64);
        assert_eq!(frame.location.as_ref().unwrap().column, 15003);
    }

    #[test]
    fn it_rejects_invalid_error_props() {
        let raw: &'static str = r#"{
            "$exception_list": []
        }"#;

        let props: Result<RawExceptionProperties, Error> = serde_json::from_str(raw);
        assert!(props.is_ok());
        assert_eq!(props.unwrap().exception_list.len(), 0);

        let raw: &'static str = r#"{
            "$exception_list": [{
                "type": "UnhandledRejection"
            }]
        }"#;

        // We support default values
        let props: RawExceptionProperties =
            serde_json::from_str(raw).expect("Can deserialize with missing value");
        assert_eq!(props.exception_list[0].exception_message, "");

        let raw: &'static str = r#"{
            "$exception_list": [{
                "typo": "UnhandledRejection",
                "value": "x"
            }]
        }"#;

        let props: Result<RawExceptionProperties, Error> = serde_json::from_str(raw);
        assert!(props.is_err());
        assert_eq!(
            props.unwrap_err().to_string(),
            "missing field `type` at line 5 column 13"
        );
    }

    fn processed_properties_json(exception_list: Value) -> Value {
        json!({
            "$exception_list": exception_list,
            "$exception_fingerprint": "",
            "$exception_fingerprint_record": [],
            "$exception_issue_id": Uuid::nil(),
            "$exception_handled": false,
            "$exception_types": ["Error"],
            "$exception_values": ["boom"],
            "$exception_sources": [],
            "$exception_functions": [],
            "passthrough": {"kept": true},
        })
    }

    #[test]
    fn processed_properties_validate_stable_wire_invariants() {
        let value = processed_properties_json(json!([{"type": "Error", "value": "boom"}]));
        let properties: ProcessedExceptionProperties =
            serde_json::from_value(value.clone()).expect("compatible processed properties");

        assert_eq!(properties.fingerprint(), "");
        assert!(properties.fingerprint_record().is_empty());
        assert_eq!(properties.issue_id(), Uuid::nil());
        assert_eq!(properties.types(), ["Error"]);
        assert_eq!(properties.values(), ["boom"]);
        assert_eq!(properties.properties()["passthrough"]["kept"], true);
        assert_eq!(serde_json::to_value(properties).unwrap(), value);

        let mut empty_manual =
            processed_properties_json(json!([{"type": "Error", "value": "boom"}]));
        empty_manual["$exception_fingerprint_record"] = json!([{"type": "manual"}]);
        let manual: ProcessedExceptionProperties = serde_json::from_value(empty_manual).unwrap();
        assert_eq!(manual.fingerprint(), "");

        let empty = processed_properties_json(json!([]));
        let error = serde_json::from_value::<ProcessedExceptionProperties>(empty).unwrap_err();
        assert!(error
            .to_string()
            .contains("processed exception list must not be empty"));
    }

    #[test]
    fn unique_properties_preserve_exception_list_order() {
        let make_exception = |t: &str, v: &str| Exception {
            exception_id: None,
            exception_type: t.to_string(),
            exception_message: v.to_string(),
            mechanism: None,
            module: None,
            thread_id: None,
            stack: None,
        };

        let list: ExceptionList = vec![
            make_exception("ZError", "z happened"),
            make_exception("AError", "a happened"),
            make_exception("ZError", "z happened"),
            make_exception("MError", "m happened"),
        ]
        .into();

        assert_eq!(list.get_unique_types(), vec!["ZError", "AError", "MError"]);
        assert_eq!(
            list.get_unique_messages(),
            vec!["z happened", "a happened", "m happened"]
        );
    }
}
