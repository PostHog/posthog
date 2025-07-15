use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha512};
use std::collections::{HashMap, HashSet};
use std::hash::Hash;
use uuid::Uuid;

use crate::fingerprinting::{
    Fingerprint, FingerprintBuilder, FingerprintComponent, FingerprintRecordPart,
};
use crate::frames::releases::{ReleaseInfo, ReleaseRecord};
use crate::frames::{Frame, RawFrame};

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Mechanism {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub handled: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(rename = "type")]
    pub mechanism_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub synthetic: Option<bool>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Stacktrace {
    Raw { frames: Vec<RawFrame> },
    Resolved { frames: Vec<Frame> },
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Exception {
    #[serde(rename = "id", skip_serializing_if = "Option::is_none")]
    pub exception_id: Option<String>,
    #[serde(rename = "type")]
    pub exception_type: String,
    #[serde(rename = "value")]
    pub exception_message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mechanism: Option<Mechanism>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub module: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thread_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none", rename = "stacktrace")]
    pub stack: Option<Stacktrace>,
}

// Given a Clickhouse Event's properties, we care about the contents
// of only a small subset. This struct is used to give us a strongly-typed
// "view" of those event properties we care about.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct RawErrProps {
    #[serde(rename = "$exception_list")]
    pub exception_list: Vec<Exception>,
    #[serde(
        rename = "$exception_fingerprint",
        skip_serializing_if = "Option::is_none"
    )]
    pub fingerprint: Option<String>, // Clients can send us fingerprints, which we'll use if present
    #[serde(flatten)]
    // A catch-all for all the properties we don't "care" about, so when we send back to kafka we don't lose any info
    pub other: HashMap<String, Value>,
}

#[derive(Debug, Clone)]
pub struct FingerprintedErrProps {
    pub exception_list: Vec<Exception>,
    pub fingerprint: Fingerprint,
    pub proposed_fingerprint: String, // We suggest a fingerprint, based on hashes, but let users override client-side
    pub other: HashMap<String, Value>,
}

// We emit this
#[derive(Debug, Serialize, Clone)]
pub struct OutputErrProps {
    #[serde(rename = "$exception_list")]
    pub exception_list: Vec<Exception>,
    #[serde(rename = "$exception_fingerprint")]
    pub fingerprint: String,
    #[serde(rename = "$exception_proposed_fingerprint")]
    pub proposed_fingerprint: String,
    #[serde(rename = "$exception_fingerprint_record")]
    pub fingerprint_record: Vec<FingerprintRecordPart>,
    #[serde(rename = "$exception_issue_id")]
    pub issue_id: Uuid,
    #[serde(flatten)]
    pub other: HashMap<String, Value>,

    // Metadata
    #[serde(rename = "$exception_handled")]
    pub handled: bool,
    #[serde(
        rename = "$exception_releases",
        skip_serializing_if = "HashMap::is_empty"
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

    pub fn to_fingerprinted(self, mut fingerprint: Fingerprint) -> FingerprintedErrProps {
        // We always track the fingerprint we'd have proposed if none was set
        let proposed_fingerprint = fingerprint.value.clone();

        // But if one was set, we use that and modify our fingerprint to reflect that
        if let Some(existing) = self.fingerprint {
            fingerprint.record.clear();
            fingerprint.record.push(FingerprintRecordPart::Manual);
            fingerprint.value = existing;
            if fingerprint.value.len() > 64 {
                let mut hasher = Sha512::default();
                hasher.update(fingerprint.value);
                fingerprint.value = format!("{:x}", hasher.finalize());
            }
            fingerprint.assignment = None;
        }

        FingerprintedErrProps {
            exception_list: self.exception_list,
            fingerprint,
            proposed_fingerprint,
            other: self.other,
        }
    }
}

impl FingerprintedErrProps {
    pub fn to_output(self, issue_id: Uuid) -> OutputErrProps {
        let frames = self
            .exception_list
            .iter()
            .filter_map(|e| e.stack.as_ref())
            .flat_map(Stacktrace::get_frames);

        let sources = unique_by(frames.clone(), |f| f.source.clone());
        let functions = unique_by(frames.clone(), |f| f.resolved_name.clone());
        let releases = ReleaseRecord::collect_to_map(frames.filter_map(|f| f.release.as_ref()));

        let types = unique_by(self.exception_list.iter(), |e| {
            Some(e.exception_type.clone())
        });
        let values = unique_by(self.exception_list.iter(), |e| {
            Some(e.exception_message.clone())
        });

        let handled = self
            .exception_list
            .first()
            .and_then(|e| e.mechanism.as_ref())
            .and_then(|m| m.handled)
            .unwrap_or(false);

        OutputErrProps {
            exception_list: self.exception_list,
            fingerprint: self.fingerprint.value,
            issue_id,
            proposed_fingerprint: self.proposed_fingerprint,
            fingerprint_record: self.fingerprint.record,
            other: self.other,

            types,
            values,
            sources,
            functions,
            handled,
            releases,
        }
    }
}

fn unique_by<T, I, F, K>(items: I, key_extractor: F) -> Vec<K>
where
    I: Iterator<Item = T>,
    F: Fn(T) -> Option<K>,
    K: Eq + Hash + Clone,
{
    items
        .filter_map(key_extractor)
        .collect::<HashSet<_>>()
        .into_iter()
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
    pub fn resolve(&self, lookup_table: &HashMap<String, Frame>) -> Option<Self> {
        let Stacktrace::Raw { frames } = self else {
            return Some(self.clone());
        };

        let mut resolved_frames = Vec::with_capacity(frames.len());
        for frame in frames {
            match lookup_table.get(&frame.frame_id()) {
                Some(resolved_frame) => resolved_frames.push(resolved_frame.clone()),
                None => return None,
            }
        }

        Some(Stacktrace::Resolved {
            frames: resolved_frames,
        })
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

    use super::RawErrProps;

    #[test]
    fn it_deserialises_error_props() {
        let raw: &'static str = include_str!("../../tests/static/raw_ch_exception_list.json");

        let raw: ClickHouseEvent = serde_json::from_str(raw).unwrap();

        let props: RawErrProps = serde_json::from_str(&raw.properties.unwrap()).unwrap();
        let exception_list = &props.exception_list;

        assert_eq!(exception_list.len(), 1);
        assert_eq!(
            exception_list[0].exception_type,
            "UnhandledRejection".to_string()
        );
        assert_eq!(
            exception_list[0].exception_message,
            "Unexpected usage".to_string()
        );
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

        let props: Result<RawErrProps, Error> = serde_json::from_str(raw);
        assert!(props.is_err());
        assert_eq!(
            props.unwrap_err().to_string(),
            "missing field `value` at line 4 column 13"
        );

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
}
