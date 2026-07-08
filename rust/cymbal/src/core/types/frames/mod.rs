use std::collections::HashMap;

use common_types::error_tracking::{FrameData, FrameId, RawFrameId};
use releases::ReleaseRecord;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    langs::{
        apple::RawAppleFrame,
        custom::CustomFrame,
        dart::RawDartFrame,
        go::RawGoFrame,
        hermes::RawHermesFrame,
        java::RawJavaFrame,
        js::RawJSFrame,
        native::{DebugImage, RawNativeFrame},
        node::RawNodeFrame,
        php::RawPHPFrame,
        python::RawPythonFrame,
        ruby::RawRubyFrame,
    },
    metric_consts::FRAME_NOT_RESOLVED,
    sanitize_source_line,
};

/// Records the metric and tracing line for a single failed-frame construction. Each
/// language-specific `From<(&RawFrame, Err, ...)> for Frame` impl calls this with the
/// typed error in scope, so we don't have to round-trip the typed error through the
/// `Frame` struct just to recover the metric reason later.
pub(crate) fn record_frame_resolution_failure(
    lang: &'static str,
    reason: &'static str,
    err: &dyn std::fmt::Display,
) {
    metrics::counter!(FRAME_NOT_RESOLVED, "lang" => lang, "reason" => reason).increment(1);
    match reason {
        "network_error" | "invalid_data" | "symbol_not_found" => {
            tracing::warn!(lang = lang, reason = reason, error = %err, "frame resolution failed");
        }
        _ => {
            tracing::debug!(lang = lang, reason = reason, error = %err, "frame resolution failed");
        }
    }
}

pub mod releases;

// We consume a huge variety of differently shaped stack frames, which we have special-case
// transformation for, to produce a single, unified representation of a frame.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(tag = "platform")]
pub enum RawFrame {
    #[serde(rename = "python")]
    Python(RawPythonFrame),
    #[serde(rename = "ruby")]
    Ruby(RawRubyFrame),
    #[serde(rename = "web:javascript")]
    JavaScriptWeb(RawJSFrame),
    #[serde(rename = "node:javascript")]
    JavaScriptNode(RawNodeFrame),
    #[serde(rename = "go")]
    Go(RawGoFrame),
    #[serde(rename = "php")]
    Php(RawPHPFrame),
    #[serde(rename = "hermes")]
    Hermes(RawHermesFrame),
    #[serde(rename = "java")]
    Java(RawJavaFrame),
    #[serde(rename = "dart")]
    Dart(RawDartFrame),
    #[serde(rename = "apple")]
    Apple(RawAppleFrame),
    // "rust" accepted defensively: the pre-release Rust SDK emitted it as a
    // pass-through frame shape that RawNativeFrame handles identically.
    #[serde(rename = "native", alias = "rust")]
    Native(RawNativeFrame),
    #[serde(rename = "custom")]
    Custom(CustomFrame),
    // TODO - remove once we're happy no clients are using this anymore
    #[serde(rename = "javascript")]
    LegacyJS(RawJSFrame),
}

impl RawFrame {
    pub fn symbol_set_ref(&self, debug_images: &[DebugImage]) -> Option<String> {
        match self {
            RawFrame::JavaScriptWeb(frame) | RawFrame::LegacyJS(frame) => frame.symbol_set_ref(),
            RawFrame::JavaScriptNode(frame) => frame.chunk_id.clone(),
            RawFrame::Hermes(frame) => frame.symbol_set_ref(),
            RawFrame::Java(frame) => frame.symbol_set_ref(),
            // Native frames (apple, rust) resolve against an uploaded debug
            // symbol set keyed by the matched debug image's debug_id. Surfacing
            // it as the symbol-set ref links the saved frame records to that
            // set, so release info attaches and a later (re)upload invalidates
            // the cached records.
            RawFrame::Apple(frame) => frame.symbol_set_ref(debug_images),
            RawFrame::Native(frame) => frame.symbol_set_ref(debug_images),
            // Frames with no symbol sets
            RawFrame::Python(_)
            | RawFrame::Php(_)
            | RawFrame::Ruby(_)
            | RawFrame::Go(_)
            | RawFrame::Dart(_)
            | RawFrame::Custom(_) => None,
        }
    }

    pub fn raw_id(&self, team_id: i32, debug_images: &[DebugImage]) -> RawFrameId {
        let hash_id = match self {
            RawFrame::JavaScriptWeb(raw) | RawFrame::LegacyJS(raw) => raw.frame_id(),
            RawFrame::JavaScriptNode(raw) => raw.frame_id(),
            RawFrame::Php(raw) => raw.frame_id(),
            RawFrame::Python(raw) => raw.frame_id(),
            RawFrame::Ruby(raw) => raw.frame_id(),
            RawFrame::Go(raw) => raw.frame_id(),
            RawFrame::Native(raw) => raw.frame_id(debug_images),
            RawFrame::Custom(raw) => raw.frame_id(),
            RawFrame::Hermes(raw) => raw.frame_id(),
            RawFrame::Java(raw) => raw.frame_id(),
            RawFrame::Dart(raw) => raw.frame_id(),
            RawFrame::Apple(raw) => raw.frame_id(debug_images),
        };

        RawFrameId::new(hash_id, team_id)
    }

    pub fn frame_id(&self, team_id: i32, index: usize, debug_images: &[DebugImage]) -> FrameId {
        self.raw_id(team_id, debug_images).to_full(index as i32)
    }

    pub fn is_suspicious(&self) -> bool {
        match self {
            RawFrame::JavaScriptWeb(frame) => frame.is_suspicious(),
            _ => false,
        }
    }
}

// We emit a single, unified representation of a frame, which is what we pass on to users.
#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct Frame {
    // Renamed for legacy reasons - resolved frames have a full FrameId, not a RawFrameId
    #[serde(rename = "raw_id")]
    pub frame_id: FrameId, // The frame id this was resolved from. This has a custom serde impl to be string represented, and drops team_id on serialization
    pub mangled_name: String, // Mangled name of the function
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<u32>, // Line the function is define on, if known
    #[serde(skip_serializing_if = "Option::is_none")]
    pub column: Option<u32>, // Column the function is defined on, if known
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>, // Generally, the file name or source file path the function is defined in.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub module: Option<String>, // The module the function is defined in, if known. Can include things like class names, namespaces, etc.
    pub in_app: bool, // We hard-require clients to tell us this?
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolved_name: Option<String>, // The name of the function, after symbolification
    pub lang: String, // The language of the frame. Always known (I guess?)
    pub resolved: bool, // Did we manage to resolve the frame?
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub resolve_failure: Option<String>, // If we failed to resolve the frame, why? Plain string so it round-trips cleanly through PG/JSON; the typed metric label is emitted at construction time via `record_frame_resolution_failure`.

    #[serde(default)] // Defaults to false
    pub synthetic: bool, // Some SDKs construct stack traces, or partially reconstruct them. This flag indicates whether the frame is synthetic or not.

    #[serde(default)] // Defaults to false
    pub suspicious: bool, // We mark some frames as suspicious if we think they might be from our own SDK code.

    // Random extra/internal data we want to tag onto frames, e.g. the raw input. For debugging
    // purposes, all production code should assume this is None
    #[serde(skip_serializing_if = "Option::is_none")]
    pub junk_drawer: Option<HashMap<String, Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code_variables: Option<Value>,
    // The lines of code surrounding the frame ptr, if known. We skip serialising this because
    // it should never go in clickhouse / be queried over, but we do store it in PG for
    // use in the frontend
    #[serde(skip)]
    pub context: Option<Context>,
    #[serde(skip)]
    pub release: Option<ReleaseRecord>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct Context {
    pub before: Vec<ContextLine>,
    pub line: ContextLine,
    pub after: Vec<ContextLine>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct ContextLine {
    pub number: u32,
    pub line: String,
}

impl Frame {
    pub fn add_junk<T>(&mut self, key: impl ToString, val: T) -> Result<(), serde_json::Error>
    where
        T: Serialize,
    {
        let key = key.to_string();
        let val = serde_json::to_value(val)?;
        self.junk_drawer
            .get_or_insert_with(HashMap::new)
            .insert(key, val);

        Ok(())
    }
}

impl ContextLine {
    pub fn new(number: u32, line: impl ToString) -> Self {
        let line = line.to_string();
        // We limit context line length to 300 chars
        let mut constrained: String = line.to_string().chars().take(300).collect();
        if line.len() > constrained.len() {
            constrained.push_str("...✂️");
        }
        // Use sanitize_source_line, not sanitize_string: source code indentation
        // (spaces, tabs) is meaningful and must not be collapsed.
        Self {
            number,
            line: sanitize_source_line(constrained),
        }
    }

    pub fn new_rel(baseline: u32, offset: i32, line: impl ToString) -> Self {
        let line = line.to_string();
        // We limit context line length to 300 chars
        let mut constrained: String = line.to_string().chars().take(300).collect();
        if line.len() > constrained.len() {
            constrained.push_str("...✂️");
        }

        let number = if offset >= 0 {
            baseline.saturating_add(offset as u32)
        } else {
            baseline.saturating_sub((-offset) as u32)
        };

        // Use sanitize_source_line, not sanitize_string: source code indentation
        // (spaces, tabs) is meaningful and must not be collapsed.
        Self {
            number,
            line: sanitize_source_line(constrained),
        }
    }
}

impl std::fmt::Display for Frame {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        writeln!(f, "Frame {}:", self.frame_id)?;

        // Function name and location
        write!(
            f,
            "  {} (from {}) ",
            self.resolved_name.as_deref().unwrap_or("unknown"),
            self.mangled_name
        )?;

        if let Some(source) = &self.source {
            write!(f, "in {source}")?;
            match (self.line, self.column) {
                (Some(line), Some(column)) => writeln!(f, ":{line}:{column}"),
                (Some(line), None) => writeln!(f, ":{line}"),
                (None, Some(column)) => writeln!(f, ":?:{column}"),
                (None, None) => writeln!(f),
            }?;
        } else {
            writeln!(f, "in unknown location")?;
        }

        // Metadata
        writeln!(f, "  in_app: {}", self.in_app)?;
        writeln!(f, "  lang: {}", self.lang)?;
        writeln!(f, "  resolved: {}", self.resolved)?;
        writeln!(
            f,
            "  resolve_failure: {}",
            self.resolve_failure.as_deref().unwrap_or("no failure")
        )?;

        // Context
        writeln!(f, "  context:")?;
        if let Some(context) = &self.context {
            for line in &context.before {
                writeln!(f, "    {}: {}", line.number, line.line)?;
            }
            writeln!(f, "  > {}: {}", context.line.number, context.line.line)?;
            for line in &context.after {
                writeln!(f, "    {}: {}", line.number, line.line)?;
            }
        } else {
            writeln!(f, "    no context")?;
        }

        // Junk drawer
        writeln!(f, "  junk drawer:")?;
        if let Some(junk) = &self.junk_drawer {
            if junk.is_empty() {
                writeln!(f, "    no junk")?;
            } else {
                for (key, value) in junk {
                    writeln!(f, "    {key}: {value}")?;
                }
            }
        } else {
            writeln!(f, "    no junk")?;
        }

        Ok(())
    }
}

impl From<Frame> for FrameData {
    fn from(frame: Frame) -> Self {
        FrameData {
            frame_id: frame.frame_id.clone(),
            synthetic: frame.synthetic,
            resolved_name: frame.resolved_name,
            mangled_name: frame.mangled_name,
            source: frame.source,
            resolved: frame.resolved,
            in_app: frame.in_app,
            line: frame.line,
            column: frame.column,
            lang: frame.lang,
            code_variables: frame.code_variables,
        }
    }
}

#[cfg(test)]
mod test {
    use crate::frames::{Frame, RawFrame};

    #[test]
    fn ensure_custom_frames_work() {
        let data = r#"
            {
            "function": "Task.Supervised.invoke_mfa/2",
            "module": "Task.Supervised",
            "filename": "lib/task/supervised.ex",
            "resolved": false,
            "in_app": true,
            "lineno": 105,
            "platform": "custom",
            "lang": "elixir"
            }
            "#;

        let frame: RawFrame = serde_json::from_str(data).unwrap();
        match frame {
            RawFrame::Custom(_) => {}
            _ => panic!("Expected a custom frame"),
        }
    }

    #[test]
    fn ensure_native_frames_parse_and_pass_through() {
        let data = r#"
            {
            "function": "checkout::payment::charge",
            "module": "checkout_service",
            "filename": "src/main.rs",
            "lang": "rust",
            "in_app": true,
            "lineno": 42,
            "instruction_addr": "0x7f3a9c041b2d",
            "image_addr": "0x7f3a9c000000",
            "platform": "native"
            }
            "#;

        let frame: RawFrame = serde_json::from_str(data).unwrap();
        match frame {
            RawFrame::Native(frame) => {
                let resolved: Frame = (&frame).into();
                assert_eq!(resolved.lang, "rust");
                assert_eq!(resolved.mangled_name, "checkout::payment::charge");
                assert_eq!(
                    resolved.resolved_name.as_deref(),
                    Some("checkout::payment::charge")
                );
                assert_eq!(resolved.source.as_deref(), Some("src/main.rs"));
                assert_eq!(resolved.module.as_deref(), Some("checkout_service"));
                assert_eq!(resolved.line, Some(42));
                assert_eq!(resolved.context, None);
                assert!(resolved.resolved);

                let missing_function_data =
                    data.replace("\"function\": \"checkout::payment::charge\",\n", "");
                let missing_function_frame: RawFrame =
                    serde_json::from_str(&missing_function_data).unwrap();
                match missing_function_frame {
                    RawFrame::Native(frame) => {
                        let resolved: Frame = (&frame).into();
                        assert_eq!(resolved.mangled_name, "");
                        assert_eq!(resolved.resolved_name, None);
                        assert!(!resolved.resolved);
                        assert_eq!(resolved.source.as_deref(), Some("src/main.rs"));
                        assert_eq!(resolved.line, Some(42));
                    }
                    _ => panic!("Expected a native frame"),
                }
            }
            _ => panic!("Expected a native frame"),
        }
    }
}
