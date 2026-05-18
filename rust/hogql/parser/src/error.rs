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
}

#[derive(Debug, Clone, Copy)]
#[allow(dead_code)] // `NotImplemented` is reserved for future
                    // deferred-feature stubs (e.g. when new grammar
                    // rules land in cpp that this parser hasn't
                    // caught up to yet) — keep the variant + helper
                    // around so callers can opt back in without
                    // adding back the enum case.
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
        }
    }

    #[allow(dead_code)] // Reserved for deferred-feature stubs; see
                        // `ErrorKind` for context.
    pub fn not_implemented(message: impl Into<String>, start: usize, end: usize) -> Self {
        Self {
            message: message.into(),
            start,
            end,
            kind: ErrorKind::NotImplemented,
        }
    }

    pub fn to_json_string(&self) -> String {
        let value = json!({
            "error": true,
            "type": self.kind.type_str(),
            "message": self.message,
            "start": {"offset": self.start},
            "end": {"offset": self.end},
        });
        // serde_json::to_string never fails for a Value, but be explicit.
        serde_json::to_string(&value).unwrap_or_else(|_| {
            r#"{"error":true,"type":"InternalError","message":"failed to serialize error envelope","start":{"offset":0},"end":{"offset":0}}"#.to_string()
        })
    }
}
