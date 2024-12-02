use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha512};

use crate::{
    error::UnhandledError,
    langs::{js::RawJSFrame, python::RawPythonFrame},
    metric_consts::PER_FRAME_TIME,
    symbol_store::Catalog,
};

pub mod records;
pub mod resolver;

// We consume a huge variety of differently shaped stack frames, which we have special-case
// transformation for, to produce a single, unified representation of a frame.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(tag = "platform")]
pub enum RawFrame {
    #[serde(rename = "python")]
    Python(RawPythonFrame),
    #[serde(rename = "web:javascript")]
    JavaScript(RawJSFrame),
    // TODO - remove once we're happy no clients are using this anymore
    #[serde(rename = "javascript")]
    LegacyJS(RawJSFrame),
}

impl RawFrame {
    pub async fn resolve(&self, team_id: i32, catalog: &Catalog) -> Result<Frame, UnhandledError> {
        let frame_resolve_time = common_metrics::timing_guard(PER_FRAME_TIME, &[]);
        let (res, lang_tag) = match self {
            RawFrame::JavaScript(frame) | RawFrame::LegacyJS(frame) => {
                (frame.resolve(team_id, catalog).await, "javascript")
            }

            RawFrame::Python(frame) => (Ok(frame.into()), "python"),
        };

        // The raw id of the frame is set after it's resolved
        let res = res.map(|mut f| {
            f.raw_id = self.frame_id();
            f
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
            RawFrame::JavaScript(frame) | RawFrame::LegacyJS(frame) => {
                frame.source_url().map(String::from).ok()
            }
            RawFrame::Python(_) => None, // Python frames don't have symbol sets
        }
    }

    pub fn frame_id(&self) -> String {
        match self {
            RawFrame::JavaScript(raw) | RawFrame::LegacyJS(raw) => raw.frame_id(),
            RawFrame::Python(raw) => raw.frame_id(),
        }
    }
}

// We emit a single, unified representation of a frame, which is what we pass on to users.
#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct Frame {
    // Properties used in processing
    pub raw_id: String,                  // The raw frame id this was resolved from
    pub mangled_name: String,            // Mangled name of the function
    pub line: Option<u32>,               // Line the function is define on, if known
    pub column: Option<u32>,             // Column the function is defined on, if known
    pub source: Option<String>,          // Generally, the file the function is defined in
    pub in_app: bool,                    // We hard-require clients to tell us this?
    pub resolved_name: Option<String>,   // The name of the function, after symbolification
    pub lang: String,                    // The language of the frame. Always known (I guess?)
    pub resolved: bool,                  // Did we manage to resolve the frame?
    pub resolve_failure: Option<String>, // If we failed to resolve the frame, why?

    // Random extra/internal data we want to tag onto frames, e.g. the raw input. For debugging
    // purposes, all production code should assume this is None
    #[serde(skip_serializing_if = "Option::is_none")]
    pub junk_drawer: Option<HashMap<String, Value>>,
    // The lines of code surrounding the frame ptr, if known. We skip serialising this because
    // it should never go in clickhouse / be queried over, but we do store it in PG for
    // use in the frontend
    #[serde(skip)]
    pub context: Option<Context>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct Context {
    pub before: Vec<ContextLine>,
    pub line: ContextLine,
    pub after: Vec<ContextLine>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct ContextLine {
    number: u32,
    line: String,
}

impl Frame {
    pub fn include_in_fingerprint(&self, h: &mut Sha512) {
        if let Some(resolved) = &self.resolved_name {
            h.update(resolved.as_bytes());
            if let Some(s) = self.source.as_ref() {
                h.update(s.as_bytes())
            }
            return;
        }

        h.update(self.mangled_name.as_bytes());

        if let Some(source) = &self.source {
            h.update(source.as_bytes());
        }

        if let Some(line) = self.line {
            h.update(line.to_string().as_bytes());
        }

        if let Some(column) = self.column {
            h.update(column.to_string().as_bytes());
        }

        h.update(self.lang.as_bytes());
    }

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
            line: constrained,
        }
    }
}

impl std::fmt::Display for Frame {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        writeln!(f, "Frame {}:", self.raw_id)?;

        // Function name and location
        write!(
            f,
            "  {} (from {}) ",
            self.resolved_name.as_deref().unwrap_or("unknown"),
            self.mangled_name
        )?;

        if let Some(source) = &self.source {
            write!(f, "in {}", source)?;
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
                    writeln!(f, "    {}: {}", key, value)?;
                }
            }
        } else {
            writeln!(f, "    no junk")?;
        }

        Ok(())
    }
}
