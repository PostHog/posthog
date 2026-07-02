use common_types::error_tracking::RawFrameId;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::hash::Hash;
use std::ops::{Deref, DerefMut};
use uuid::Uuid;

use crate::fingerprinting::{
    FingerprintBuilder, FingerprintComponent, FingerprintRecordPart, VersionedFingerprint,
};
use crate::frames::releases::{ReleaseInfo, ReleaseRecord};
use crate::frames::{Frame, RawFrame};
use crate::langs::native::DebugImage;
use crate::metric_consts::POSTHOG_SDK_EXCEPTION_RESOLVED;

pub mod batch;
pub mod event;
pub mod exception_properties;
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

// Given a Clickhouse Event's properties, we care about the contents
// of only a small subset. This struct is used to give us a strongly-typed
// "view" of those event properties we care about.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct RawErrProps {
    #[serde(rename = "$exception_list")]
    pub exception_list: ExceptionList,
    #[serde(
        rename = "$exception_fingerprint",
        skip_serializing_if = "Option::is_none"
    )]
    pub fingerprint: Option<String>, // Clients can send us fingerprints, which we'll use if present
    #[serde(rename = "$issue_name", skip_serializing_if = "Option::is_none")]
    pub issue_name: Option<String>, // Clients can send us custom issue names, which we'll use if present
    #[serde(rename = "$issue_description", skip_serializing_if = "Option::is_none")]
    pub issue_description: Option<String>, // Clients can send us custom issue descriptions, which we'll use if present
    #[serde(rename = "$exception_handled", skip_serializing_if = "Option::is_none")]
    pub handled: Option<bool>, // Clients can send us handled status, which we'll use if present
    #[serde(
        rename = "$debug_images",
        default,
        skip_serializing_if = "Vec::is_empty"
    )]
    pub debug_images: Vec<DebugImage>, // Debug images sent by native SDKs (apple, rust) for symbolication
    #[serde(flatten)]
    // A catch-all for all the properties we don't "care" about, so when we send back to kafka we don't lose any info
    pub other: HashMap<String, Value>,
}

impl RawErrProps {
    pub fn add_error_message(&mut self, msg: impl ToString) {
        let mut errors = match self.other.remove("$cymbal_errors") {
            Some(serde_json::Value::Array(errors)) => errors,
            _ => Vec::new(),
        };

        errors.push(serde_json::Value::String(msg.to_string()));

        self.other.insert(
            "$cymbal_errors".to_string(),
            serde_json::Value::Array(errors),
        );
    }
}

// We emit this
#[derive(Debug, Default, Serialize, Deserialize, Clone)]
pub struct OutputErrProps {
    #[serde(rename = "$exception_list")]
    pub exception_list: ExceptionList,
    #[serde(rename = "$exception_fingerprint")]
    pub fingerprint: String,
    #[serde(rename = "$exception_proposed_fingerprint")]
    pub proposed_fingerprint: String,
    #[serde(rename = "$exception_fingerprint_record")]
    pub fingerprint_record: Vec<FingerprintRecordPart>,
    // Every registered algorithm version's fingerprint with its record of hashed components.
    // `$exception_fingerprint` above is the one that actually resolved the issue.
    #[serde(
        rename = "$exception_fingerprints",
        skip_serializing_if = "Vec::is_empty",
        default
    )]
    pub fingerprints: Vec<VersionedFingerprint>,
    #[serde(rename = "$exception_issue_id")]
    pub issue_id: Uuid,
    #[serde(flatten)]
    pub other: HashMap<String, Value>,

    // Metadata
    #[serde(rename = "$exception_handled")]
    pub handled: bool,
    #[serde(
        rename = "$exception_releases",
        skip_serializing_if = "HashMap::is_empty",
        default
    )]
    pub releases: HashMap<String, ReleaseInfo>,
    // Search metadata (materialized)
    #[serde(rename = "$exception_types")]
    pub types: Vec<String>,
    #[serde(rename = "$exception_values")]
    pub values: Vec<String>,
    #[serde(rename = "$exception_sources")]
    pub sources: Vec<String>,
    #[serde(rename = "$exception_functions")]
    pub functions: Vec<String>,
}

impl FingerprintComponent for Exception {
    fn update(&self, fp: &mut FingerprintBuilder) {
        let mut pieces = vec![];
        fp.update(self.exception_type.as_bytes());
        pieces.push("Exception Type".to_string());
        if !matches!(self.stack, Some(Stacktrace::Resolved { frames: _ })) {
            fp.update(self.exception_message.as_bytes());
            pieces.push("Exception Message".to_string());
        };
        fp.add_part(FingerprintRecordPart::Exception {
            id: self.exception_id.clone(),
            pieces,
        });
    }
}

impl Exception {
    pub fn include_in_fingerprint(&self, fp: &mut FingerprintBuilder) {
        self.update(fp);

        let Some(Stacktrace::Resolved { frames }) = &self.stack else {
            return;
        };

        let has_no_resolved = !frames.iter().any(|f| f.resolved);
        let has_no_in_app = !frames.iter().any(|f| f.in_app);

        if has_no_in_app {
            // TODO: we should try to be smarter about handling the case when
            // there are no in-app frames
            if let Some(f) = frames.first() {
                f.update(fp)
            }
            return;
        }

        for frame in frames {
            if (has_no_resolved || frame.resolved) && frame.in_app {
                frame.update(fp)
            }
        }
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

impl OutputErrProps {
    pub fn add_error_message(&mut self, msg: impl ToString) {
        let mut errors = match self.other.remove("$cymbal_errors") {
            Some(serde_json::Value::Array(errors)) => errors,
            _ => Vec::new(),
        };

        errors.push(serde_json::Value::String(msg.to_string()));

        self.other.insert(
            "$cymbal_errors".to_string(),
            serde_json::Value::Array(errors),
        );
    }

    pub fn strip_frame_junk(&mut self) {
        self.exception_list.iter_mut().for_each(|exception| {
            if let Some(Stacktrace::Resolved { frames }) = &mut exception.stack {
                frames.iter_mut().for_each(|frame| frame.junk_drawer = None);
            }
        });
    }
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
    use serde_json::Error;

    use crate::{frames::RawFrame, types::Stacktrace};

    use super::{Exception, ExceptionList, RawErrProps};

    #[test]
    fn it_deserialises_error_props() {
        let raw: &'static str = include_str!("../../../../tests/static/raw_ch_exception_list.json");

        let raw: ClickHouseEvent = serde_json::from_str(raw).unwrap();

        let props: RawErrProps = serde_json::from_str(&raw.properties.unwrap()).unwrap();
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

        let props: Result<RawErrProps, Error> = serde_json::from_str(raw);
        assert!(props.is_ok());
        assert_eq!(props.unwrap().exception_list.len(), 0);

        let raw: &'static str = r#"{
            "$exception_list": [{
                "type": "UnhandledRejection"
            }]
        }"#;

        // We support default values
        let props: RawErrProps =
            serde_json::from_str(raw).expect("Can deserialize with missing value");
        assert_eq!(props.exception_list[0].exception_message, "");

        let raw: &'static str = r#"{
            "$exception_list": [{
                "typo": "UnhandledRejection",
                "value": "x"
            }]
        }"#;

        let props: Result<RawErrProps, Error> = serde_json::from_str(raw);
        assert!(props.is_err());
        assert_eq!(
            props.unwrap_err().to_string(),
            "missing field `type` at line 5 column 13"
        );
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
