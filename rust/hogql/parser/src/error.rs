//! Error type + JSON envelope serialisation matching the existing C++
//! parser's error shape in [`common/hogql_parser/parser_json.cpp`]. The
//! Python side ([`posthog/hogql/json_ast.py`]) special-cases this envelope
//! and raises `ExposedHogQLError` / `SyntaxError` from it.

use serde_json::json;

#[derive(Debug, Clone)]
pub struct ParseError {
    pub message: String,
    pub start: usize,
    pub end: usize,
    /// Maps to the JSON `type` field. The Python deserialiser branches on it:
    /// `"SyntaxError"` with `"reserved keyword"` in the message becomes
    /// `HogQLSyntaxError`; everything else becomes `ExposedHogQLError`.
    pub kind: ErrorKind,
    /// `true` when this error must not be rolled back by `try_alt` — the
    /// alternative parsed past its commit point and the failure is
    /// final. cpp's ANTLR doesn't have rollback in this scenario; the
    /// alt that would have fallen back instead emits a visitor-level
    /// `NotImplementedError`. Used by INTERVAL combined-string
    /// validation, where the string content was definitively assigned
    /// to the INTERVAL form and the count / unit must validate.
    pub fatal: bool,
}

#[derive(Debug, Clone, Copy)]
pub enum ErrorKind {
    Syntax,
    NotImplemented,
}

impl ErrorKind {
    fn type_str(self) -> &'static str {
        match self {
            ErrorKind::Syntax => "SyntaxError",
            ErrorKind::NotImplemented => "NotImplementedError",
        }
    }
}

impl ParseError {
    pub fn syntax(message: impl Into<String>, start: usize, end: usize) -> Self {
        Self {
            message: message.into(),
            start,
            end,
            kind: ErrorKind::Syntax,
            fatal: false,
        }
    }

    pub fn not_implemented(message: impl Into<String>, start: usize, end: usize) -> Self {
        Self {
            message: message.into(),
            start,
            end,
            kind: ErrorKind::NotImplemented,
            fatal: false,
        }
    }

    /// Like `not_implemented`, but marks the error fatal so `try_alt` short-circuits and doesn't fall back to the next alternative.
    pub fn not_implemented_fatal(message: impl Into<String>, start: usize, end: usize) -> Self {
        Self {
            message: message.into(),
            start,
            end,
            kind: ErrorKind::NotImplemented,
            fatal: true,
        }
    }

    /// Mark an existing error fatal so `try_alt` won't roll it back. Used at a
    /// dispatch site that has committed to a single production (e.g. `INTERVAL`
    /// followed by a primary value), where any parse failure is a hard error
    /// rather than a signal to try another alternative.
    pub fn into_fatal(mut self) -> Self {
        self.fatal = true;
        self
    }

    /// Build the JSON error envelope shape. Used directly by the `parse_*_py`
    /// path (which raises a Python exception from this) and serialised to a
    /// string by [`Self::to_json_string`] for the `parse_*_json` path.
    pub fn to_json_value(&self) -> serde_json::Value {
        json!({
            "error": true,
            "type": self.kind.type_str(),
            "message": self.message,
            "start": {"offset": self.start},
            "end": {"offset": self.end},
        })
    }

    pub fn to_json_string(&self) -> String {
        // serde_json::to_string never fails for a Value, but be explicit.
        serde_json::to_string(&self.to_json_value()).unwrap_or_else(|_| {
            r#"{"error":true,"type":"InternalError","message":"failed to serialize error envelope","start":{"offset":0},"end":{"offset":0}}"#.to_string()
        })
    }
}
