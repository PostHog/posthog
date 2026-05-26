use std::{collections::HashMap, fmt::Display};

use chrono::{DateTime, Utc};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{sanitize_source_line, ReleaseRecord};

// We emit a single, unified representation of a frame, which is what we pass on to users.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RawFrame {
    #[serde(flatten)]
    pub data: serde_json::Map<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct Frame<Id = String> {
    // Keep the public serialized field name `raw_id`; resolved frames store a
    // full FrameId internally instead of a RawFrameId.
    #[serde(rename = "raw_id")]
    pub frame_id: Id, // The frame id this was resolved from.
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

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
pub struct FrameRecord<Id = String> {
    pub id: Id,
    pub created_at: DateTime<Utc>,
    pub symbol_set_id: Option<String>,
    pub contents: Frame<Id>,
    pub resolved: bool,
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
    pub number: u32,
    pub line: String,
}

impl<Id> Frame<Id> {
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

impl<Id: Display> std::fmt::Display for Frame<Id> {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn context_line_preserves_indentation() {
        let input = format!("{:>65}reason:@\"value\"", "");

        let line = ContextLine::new(1, input.clone());

        assert_eq!(line.line, input);
    }

    #[test]
    fn context_line_strips_nulls() {
        let line = ContextLine::new(1, "hello\u{0000}world");

        assert_eq!(line.line, "hello\u{FFFD}world");
    }

    #[test]
    fn frame_serialization_uses_public_raw_id_name_and_skips_internal_enrichment() {
        let frame = Frame {
            frame_id: "raw-hash/2".to_string(),
            mangled_name: "minified".to_string(),
            line: Some(10),
            column: Some(20),
            source: Some("app.js".to_string()),
            module: Some("checkout".to_string()),
            in_app: true,
            resolved_name: Some("submitOrder".to_string()),
            lang: "javascript".to_string(),
            resolved: true,
            resolve_failure: None,
            synthetic: false,
            suspicious: false,
            junk_drawer: None,
            code_variables: None,
            context: Some(Context {
                before: vec![ContextLine::new(9, "before")],
                line: ContextLine::new(10, "current"),
                after: vec![ContextLine::new(11, "after")],
            }),
            release: Some(ReleaseRecord {
                id: uuid::Uuid::nil(),
                team_id: 1,
                hash_id: "release-hash".to_string(),
                created_at: Utc::now(),
                version: "1.0.0".to_string(),
                project: "web".to_string(),
                metadata: None,
            }),
        };

        let value = serde_json::to_value(frame).unwrap();

        assert_eq!(value["raw_id"], "raw-hash/2");
        assert!(value.get("frame_id").is_none());
        assert!(value.get("context").is_none());
        assert!(value.get("release").is_none());
    }
}
