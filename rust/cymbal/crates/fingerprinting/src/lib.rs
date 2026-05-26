//! Automatic exception fingerprint generation.
//!
//! This crate owns the deterministic fallback fingerprint generated from
//! resolved exception payloads. Persistence-backed grouping rules are evaluated
//! elsewhere; matching rules can still be converted into fingerprint records here
//! to keep the output shape consistent.

pub use cymbal_domain::FingerprintRecordPart;
use cymbal_domain::{exception, ExceptionList};
use cymbal_rules::{GroupingRule, NewAssignment};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fingerprint {
    pub value: String,
    pub record: Vec<FingerprintRecordPart>,
    // DEPRECATED: assignment is never used
    #[serde(skip)]
    pub assignment: Option<NewAssignment>,
}

#[derive(Debug, Clone, Default)]
pub struct FingerprintBuilder {
    pub record: Vec<FingerprintRecordPart>,
    pub hasher: Sha512,
}

// Anything that can be included in a fingerprint should implement this.
pub trait FingerprintComponent {
    fn update(&self, fingerprint: &mut FingerprintBuilder);
}

impl FingerprintBuilder {
    pub fn update(&mut self, data: impl AsRef<[u8]>) {
        self.hasher.update(data);
    }

    pub fn add_part(&mut self, part: impl Into<FingerprintRecordPart>) {
        self.record.push(part.into());
    }

    pub fn finalize(self) -> Fingerprint {
        let result = self.hasher.finalize();
        let content = format!("{result:x}");
        Fingerprint {
            value: content,
            record: self.record,
            assignment: None,
        }
    }
}

impl Fingerprint {
    pub fn from_rule(rule: GroupingRule) -> Self {
        Self::from_rule_parts(rule.id, rule.assignment())
    }

    pub fn from_rule_parts(rule_id: Uuid, assignment: Option<NewAssignment>) -> Self {
        let content = format!("custom-rule:{rule_id}");
        Fingerprint {
            value: content,
            record: vec![FingerprintRecordPart::Custom { rule_id }],
            assignment,
        }
    }

    pub fn from_exception_list(exception_list: &ExceptionList) -> Fingerprint {
        let mut fingerprint = FingerprintBuilder::default();

        for exception in &exception_list.0 {
            include_exception_in_fingerprint(exception, &mut fingerprint);
        }

        fingerprint.finalize()
    }

    pub fn from_serializable_exception_list(
        exception_list: &impl Serialize,
    ) -> Result<Fingerprint, serde_json::Error> {
        let exception_list = serde_json::from_value(serde_json::to_value(exception_list)?)?;
        Ok(Self::from_exception_list(&exception_list))
    }

    pub fn apply_manual_override(&mut self, manual_fingerprint: &str) {
        self.record.clear();
        self.record.push(FingerprintRecordPart::Manual);
        self.value = normalize_manual_fingerprint(manual_fingerprint);
        self.assignment = None;
    }
}

pub fn normalize_manual_fingerprint(fingerprint: &str) -> String {
    if fingerprint.len() <= 64 {
        return fingerprint.to_string();
    }

    let mut hasher = Sha512::default();
    hasher.update(fingerprint);
    format!("{:x}", hasher.finalize())
}

impl FingerprintComponent for exception::Exception {
    fn update(&self, fingerprint: &mut FingerprintBuilder) {
        let mut pieces = Vec::new();
        if let Some(exception_type) = self.exception_type.as_deref() {
            fingerprint.update(exception_type.as_bytes());
            pieces.push("Exception Type".to_string());
        }
        if self.stacktrace.is_none() {
            if let Some(exception_message) = self.exception_message.as_deref() {
                fingerprint.update(exception_message.as_bytes());
                pieces.push("Exception Message".to_string());
            }
        }
        fingerprint.add_part(FingerprintRecordPart::Exception {
            id: exception_id(self),
            pieces,
        });
    }
}

impl FingerprintComponent for exception::Frame {
    fn update(&self, fingerprint: &mut FingerprintBuilder) {
        let mut included_pieces = Vec::new();

        if let Some(source) = frame_source(self) {
            fingerprint.update(source.as_bytes());
            included_pieces.push("Source file name");
        }

        if let Some(module) = string_field(self, "module") {
            fingerprint.update(module.as_bytes());
            included_pieces.push("Module name");
        }

        if let Some(resolved) = self.resolved_name.as_deref() {
            fingerprint.update(resolved.as_bytes());
            included_pieces.push("Resolved function name");
            fingerprint.add_part(frame_record_part(self, included_pieces));
            return;
        }

        if let Some(mangled_name) = frame_function(self) {
            fingerprint.update(mangled_name.as_bytes());
            included_pieces.push("Mangled function name");
        }

        if let Some(line) = integer_field(self, "line").or_else(|| integer_field(self, "lineno")) {
            fingerprint.update(line.to_string().as_bytes());
            included_pieces.push("Line number");
        }

        if let Some(column) = integer_field(self, "column").or_else(|| integer_field(self, "colno"))
        {
            fingerprint.update(column.to_string().as_bytes());
            included_pieces.push("Column number");
        }

        if let Some(lang) = string_field(self, "lang") {
            fingerprint.update(lang.as_bytes());
            included_pieces.push("Language");
        }

        fingerprint.add_part(frame_record_part(self, included_pieces));
    }
}

fn include_exception_in_fingerprint(
    exception: &exception::Exception,
    fingerprint: &mut FingerprintBuilder,
) {
    exception.update(fingerprint);

    let Some(stacktrace) = &exception.stacktrace else {
        return;
    };

    let has_no_resolved = !stacktrace.frames.iter().any(frame_resolved);
    let has_no_in_app = !stacktrace.frames.iter().any(frame_in_app);

    if has_no_in_app {
        // TODO: we should try to be smarter about handling the case when
        // there are no in-app frames.
        if let Some(frame) = stacktrace.frames.first() {
            frame.update(fingerprint);
        }
        return;
    }

    for frame in &stacktrace.frames {
        if (has_no_resolved || frame_resolved(frame)) && frame_in_app(frame) {
            frame.update(fingerprint);
        }
    }
}

fn frame_record_part(frame: &exception::Frame, pieces: Vec<&str>) -> FingerprintRecordPart {
    FingerprintRecordPart::Frame {
        raw_id: string_field(frame, "raw_id")
            .unwrap_or_default()
            .to_string(),
        pieces: pieces.into_iter().map(String::from).collect(),
    }
}

fn exception_id(exception: &exception::Exception) -> Option<String> {
    string_value(exception.other.get("exception_id"))
        .or_else(|| string_value(exception.other.get("id")))
        .map(ToString::to_string)
}

fn frame_source(frame: &exception::Frame) -> Option<&str> {
    frame.source.as_deref().or(frame.filename.as_deref())
}

fn frame_function(frame: &exception::Frame) -> Option<&str> {
    frame
        .mangled_name
        .as_deref()
        .or(frame.function_name.as_deref())
}

fn frame_resolved(frame: &exception::Frame) -> bool {
    frame
        .other
        .get("resolved")
        .and_then(serde_json::Value::as_bool)
        .unwrap_or(false)
}

fn frame_in_app(frame: &exception::Frame) -> bool {
    frame.in_app.unwrap_or(true)
}

fn string_field<'a>(frame: &'a exception::Frame, field: &str) -> Option<&'a str> {
    string_value(frame.other.get(field))
}

fn string_value(value: Option<&serde_json::Value>) -> Option<&str> {
    value
        .and_then(serde_json::Value::as_str)
        .filter(|value| !value.is_empty())
}

fn integer_field(frame: &exception::Frame, field: &str) -> Option<u64> {
    frame.other.get(field).and_then(serde_json::Value::as_u64)
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    fn exception_list(value: serde_json::Value) -> ExceptionList {
        serde_json::from_value(value).unwrap()
    }

    #[test]
    fn test_some_resolved_frames() {
        let mut exceptions = exception_list(json!([{
            "exception_id": null,
            "type": "TypeError",
            "value": "Cannot read property 'foo' of undefined",
            "stacktrace": {
                "type": "resolved",
                "frames": [
                    {
                        "raw_id": "/0",
                        "mangled_name": "foo",
                        "line": 10,
                        "column": 5,
                        "source": "http://example.com/alpha/foo.js",
                        "in_app": true,
                        "resolved_name": "bar",
                        "resolved": true,
                        "lang": "javascript"
                    },
                    {
                        "raw_id": "/0",
                        "mangled_name": "bar",
                        "line": 20,
                        "column": 15,
                        "source": "http://example.com/bar.js",
                        "in_app": true,
                        "resolved_name": "baz",
                        "resolved": true,
                        "lang": "javascript"
                    }
                ]
            }
        }]));

        let fingerprint_with_all_resolved = Fingerprint::from_exception_list(&exceptions).value;

        exceptions.0[0].stacktrace.as_mut().unwrap().frames.push(
            serde_json::from_value(json!({
                "raw_id": "/0",
                "mangled_name": "xyz",
                "line": 30,
                "column": 25,
                "in_app": true,
                "resolved": false,
                "lang": "javascript"
            }))
            .unwrap(),
        );

        let mixed_fingerprint = Fingerprint::from_exception_list(&exceptions).value;

        // In cases where there are SOME resolved frames, the fingerprint should be identical
        // to the case where all frames are resolved (unresolved frames should be ignored)
        assert_eq!(fingerprint_with_all_resolved, mixed_fingerprint);
    }

    #[test]
    fn test_no_resolved_frames() {
        let no_stack_exceptions = exception_list(json!([{
            "type": "TypeError",
            "value": "Cannot read property 'foo' of undefined"
        }]));
        let with_stack_exceptions = exception_list(json!([{
            "type": "TypeError",
            "value": "Cannot read property 'foo' of undefined",
            "stacktrace": {
                "type": "resolved",
                "frames": [
                    {
                        "raw_id": "/0",
                        "mangled_name": "foo",
                        "line": 10,
                        "column": 5,
                        "source": "http://example.com/alpha/foo.js",
                        "in_app": true,
                        "resolved_name": "bar",
                        "resolved": false,
                        "lang": "javascript"
                    },
                    {
                        "raw_id": "/0",
                        "mangled_name": "bar",
                        "line": 20,
                        "column": 15,
                        "source": "http://example.com/bar.js",
                        "in_app": true,
                        "resolved_name": "baz",
                        "resolved": false,
                        "lang": "javascript"
                    },
                    {
                        "raw_id": "/0",
                        "mangled_name": "xyz",
                        "line": 30,
                        "column": 25,
                        "in_app": true,
                        "resolved": false,
                        "lang": "javascript"
                    }
                ]
            }
        }]));

        let no_stack_fingerprint = Fingerprint::from_exception_list(&no_stack_exceptions).value;
        let with_stack_fingerprint = Fingerprint::from_exception_list(&with_stack_exceptions).value;

        // If there are NO resolved frames, fingerprinting should account for the unresolved frames
        assert_ne!(no_stack_fingerprint, with_stack_fingerprint);
    }

    #[test]
    fn test_no_in_app_frames() {
        let exception_id = Uuid::now_v7().to_string();
        let mut exceptions = exception_list(json!([{
            "exception_id": exception_id,
            "type": "TypeError",
            "value": "Cannot read property 'foo' of undefined",
            "stacktrace": {
                "type": "resolved",
                "frames": [{
                    "raw_id": "/0",
                    "mangled_name": "foo",
                    "line": 10,
                    "column": 5,
                    "source": "http://example.com/alpha/foo.js",
                    "in_app": true,
                    "resolved_name": "bar",
                    "resolved": false,
                    "lang": "javascript"
                }]
            }
        }]));

        let fingerprint_1 = Fingerprint::from_exception_list(&exceptions).value;

        exceptions.0[0].stacktrace.as_mut().unwrap().frames.push(
            serde_json::from_value(json!({
                "raw_id": "/0",
                "mangled_name": "bar",
                "line": 20,
                "column": 15,
                "source": "http://example.com/bar.js",
                "in_app": false,
                "resolved_name": "baz",
                "resolved": false,
                "lang": "javascript"
            }))
            .unwrap(),
        );

        let fingerprint_2 = Fingerprint::from_exception_list(&exceptions).value;

        // Fingerprinting should ignore non-in-app frames
        assert_eq!(fingerprint_1, fingerprint_2);
    }

    #[test]
    fn manual_fingerprints_longer_than_64_characters_are_hashed() {
        let manual = "x".repeat(65);
        let mut fingerprint = Fingerprint::from_exception_list(&ExceptionList::default());

        fingerprint.apply_manual_override(&manual);

        assert_ne!(fingerprint.value, manual);
        assert_eq!(fingerprint.value.len(), 128);
        assert_eq!(fingerprint.record, vec![FingerprintRecordPart::Manual]);
        assert!(fingerprint.assignment.is_none());
    }
}
