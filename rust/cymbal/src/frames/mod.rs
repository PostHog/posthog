use std::collections::HashMap;

use common_types::error_tracking::{FrameData, FrameId, RawFrameId};
use releases::ReleaseRecord;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    error::UnhandledError,
    fingerprinting::{FingerprintBuilder, FingerprintComponent, FingerprintRecordPart},
    langs::{
        custom::CustomFrame, dart::RawDartFrame, go::RawGoFrame, hermes::RawHermesFrame,
        java::RawJavaFrame, js::RawJSFrame, node::RawNodeFrame, python::RawPythonFrame,
        ruby::RawRubyFrame,
    },
    metric_consts::{LEGACY_JS_FRAME_RESOLVED, PER_FRAME_TIME},
    sanitize_string,
    symbol_store::Catalog,
};

pub mod records;
pub mod releases;
pub mod resolver;

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
    #[serde(rename = "hermes")]
    Hermes(RawHermesFrame),
    #[serde(rename = "java")]
    Java(RawJavaFrame),
    #[serde(rename = "dart")]
    Dart(RawDartFrame),
    #[serde(rename = "custom")]
    Custom(CustomFrame),
    // TODO - remove once we're happy no clients are using this anymore
    #[serde(rename = "javascript")]
    LegacyJS(RawJSFrame),
}

impl RawFrame {
    pub async fn resolve(
        &self,
        team_id: i32,
        catalog: &Catalog,
    ) -> Result<Vec<Frame>, UnhandledError> {
        let frame_resolve_time = common_metrics::timing_guard(PER_FRAME_TIME, &[]);
        let (res, lang_tag) = match self {
            RawFrame::JavaScriptWeb(frame) => {
                (to_vec(frame.resolve(team_id, catalog).await), "javascript")
            }
            RawFrame::LegacyJS(frame) => {
                // TODO: monitor this metric and remove the legacy frame type when it hits 0
                metrics::counter!(LEGACY_JS_FRAME_RESOLVED).increment(1);
                (to_vec(frame.resolve(team_id, catalog).await), "javascript")
            }
            RawFrame::JavaScriptNode(frame) => {
                (to_vec(frame.resolve(team_id, catalog).await), "javascript")
            }

            RawFrame::Dart(frame) => (to_vec(Ok(frame.into())), "dart"),
            RawFrame::Python(frame) => (to_vec(Ok(frame.into())), "python"),
            RawFrame::Ruby(frame) => (to_vec(Ok(frame.into())), "ruby"),
            RawFrame::Custom(frame) => (to_vec(Ok(frame.into())), "custom"),
            RawFrame::Go(frame) => (to_vec(Ok(frame.into())), "go"),
            RawFrame::Hermes(frame) => (to_vec(frame.resolve(team_id, catalog).await), "hermes"),
            RawFrame::Java(frame) => (frame.resolve(team_id, catalog).await, "java"),
        };

        // The raw id of the frame is set after it's resolved
        let res = res.map(|mut fs| {
            fs.iter_mut()
                .enumerate()
                .for_each(|(index, f)| f.frame_id = self.frame_id(team_id, index));
            fs
        });

        if res.is_err() {
            frame_resolve_time.label("outcome", "failed")
        } else {
            frame_resolve_time.label("outcome", "success")
        }
        .label("lang", lang_tag)
        .fin();

        res
    }

    pub fn symbol_set_ref(&self) -> Option<String> {
        match self {
            RawFrame::JavaScriptWeb(frame) | RawFrame::LegacyJS(frame) => frame.symbol_set_ref(),
            RawFrame::JavaScriptNode(frame) => frame.chunk_id.clone(),
            RawFrame::Hermes(frame) => frame.symbol_set_ref(),
            RawFrame::Java(frame) => frame.symbol_set_ref(),
            // Frames with no symbol sets
            RawFrame::Python(_)
            | RawFrame::Ruby(_)
            | RawFrame::Go(_)
            | RawFrame::Dart(_)
            | RawFrame::Custom(_) => None,
        }
    }

    pub fn raw_id(&self, team_id: i32) -> RawFrameId {
        let hash_id = match self {
            RawFrame::JavaScriptWeb(raw) | RawFrame::LegacyJS(raw) => raw.frame_id(),
            RawFrame::JavaScriptNode(raw) => raw.frame_id(),
            RawFrame::Python(raw) => raw.frame_id(),
            RawFrame::Ruby(raw) => raw.frame_id(),
            RawFrame::Go(raw) => raw.frame_id(),
            RawFrame::Custom(raw) => raw.frame_id(),
            RawFrame::Hermes(raw) => raw.frame_id(),
            RawFrame::Java(raw) => raw.frame_id(),
            RawFrame::Dart(raw) => raw.frame_id(),
        };

        RawFrameId::new(hash_id, team_id)
    }

    pub fn frame_id(&self, team_id: i32, index: usize) -> FrameId {
        self.raw_id(team_id).to_full(index as i32)
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolve_failure: Option<String>, // If we failed to resolve the frame, why?

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
    #[serde(skip)]
    pub exception_type: Option<String>, // Used for java exceptions, where we have to demangle the exception type, and do so alongside the frame
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

impl FingerprintComponent for Frame {
    fn update(&self, fp: &mut FingerprintBuilder) {
        let get_part = |s: &FrameId, p: Vec<&str>| FingerprintRecordPart::Frame {
            raw_id: s.to_string(),
            pieces: p.into_iter().map(String::from).collect(),
        };

        let mut included_pieces = Vec::new();

        // Include source and module in the fingerprint either way
        if let Some(source) = &self.source {
            fp.update(source.as_bytes());
            included_pieces.push("Source file name");
        }

        if let Some(module) = &self.module {
            fp.update(module.as_bytes());
            included_pieces.push("Module name");
        }

        // If we've resolved this frame, include function name, and then return
        if let Some(resolved) = &self.resolved_name {
            fp.update(resolved.as_bytes());
            included_pieces.push("Resolved function name");

            fp.add_part(get_part(&self.frame_id, included_pieces));
            return;
        }

        // Otherwise, get more granular
        fp.update(self.mangled_name.as_bytes());
        included_pieces.push("Mangled function name");

        if let Some(line) = self.line {
            fp.update(line.to_string().as_bytes());
            included_pieces.push("Line number");
        }

        if let Some(column) = self.column {
            fp.update(column.to_string().as_bytes());
            included_pieces.push("Column number");
        }

        fp.update(self.lang.as_bytes());
        included_pieces.push("Language");
        fp.add_part(get_part(&self.frame_id, included_pieces));
    }
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

        Self {
            number,
            line: sanitize_string(constrained),
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

fn to_vec<T, E>(item: Result<T, E>) -> Result<Vec<T>, E> {
    item.map(|t| vec![t])
}

#[cfg(test)]
mod test {
    use crate::frames::RawFrame;

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
}
