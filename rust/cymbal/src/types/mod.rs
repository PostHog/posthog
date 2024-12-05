use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{digest::Update, Sha512};
use uuid::Uuid;

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
    #[serde(rename = "type")]
    pub exception_type: String,
    #[serde(rename = "value")]
    pub exception_message: String,
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

pub struct FingerprintedErrProps {
    pub exception_list: Vec<Exception>,
    pub fingerprint: String,
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
    #[serde(rename = "$exception_issue_id")]
    pub issue_id: Uuid,
    #[serde(flatten)]
    pub other: HashMap<String, Value>,
}

impl Exception {
    pub fn include_in_fingerprint(&self, h: &mut Sha512) {
        h.update(self.exception_type.as_bytes());
        let Some(Stacktrace::Resolved { frames }) = &self.stack else {
            h.update(self.exception_message.as_bytes());
            return;
        };

        let has_no_resolved = !frames.iter().any(|f| f.resolved);
        let has_no_in_app = !frames.iter().any(|f| f.in_app);

        if has_no_in_app {
            // TODO: we should try to be smarter about handling the case when
            // there are no in-app frames
            if let Some(f) = frames.first() {
                f.include_in_fingerprint(h)
            }
            return;
        }

        for frame in frames {
            if (has_no_resolved || frame.resolved) && frame.in_app {
                frame.include_in_fingerprint(h)
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

    pub fn to_fingerprinted(self, fingerprint: String) -> FingerprintedErrProps {
        FingerprintedErrProps {
            exception_list: self.exception_list,
            fingerprint: self.fingerprint.unwrap_or(fingerprint.clone()),
            proposed_fingerprint: fingerprint,
            other: self.other,
        }
    }
}

impl FingerprintedErrProps {
    pub fn to_output(self, issue_id: Uuid) -> OutputErrProps {
        OutputErrProps {
            exception_list: self.exception_list,
            fingerprint: self.fingerprint,
            issue_id,
            proposed_fingerprint: self.proposed_fingerprint,
            other: self.other,
        }
    }
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
        let RawFrame::JavaScript(frame) = &frames[0] else {
            panic!("Expected a JavaScript frame")
        };

        assert_eq!(
            frame.source_url,
            Some("https://app-static.eu.posthog.com/static/chunk-PGUQKT6S.js".to_string())
        );
        assert_eq!(frame.fn_name, "?".to_string());
        assert!(frame.in_app);
        assert_eq!(frame.location.as_ref().unwrap().line, 64);
        assert_eq!(frame.location.as_ref().unwrap().column, 25112);

        let RawFrame::JavaScript(frame) = &frames[1] else {
            panic!("Expected a JavaScript frame")
        };
        assert_eq!(
            frame.source_url,
            Some("https://app-static.eu.posthog.com/static/chunk-PGUQKT6S.js".to_string())
        );
        assert_eq!(frame.fn_name, "n.loadForeignModule".to_string());
        assert!(frame.in_app);
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
