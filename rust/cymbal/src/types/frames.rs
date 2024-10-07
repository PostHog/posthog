use serde::{Deserialize, Serialize};
use sourcemap::Token;

use crate::{langs::js::RawJSFrame, traits::SymbolSetRef};

// We consume a huge variety of differently shaped stack frames, which we have special-case
// transformation for, to produce a single, unified representation of a frame.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub enum RawFrame {
    JavaScript(RawJSFrame),
}

impl RawFrame {
    pub fn source_ref(&self, team_id: i32) -> SymbolSetRef {
        let RawFrame::JavaScript(raw) = self;
        let id = raw.source_ref();
        SymbolSetRef { team_id, id }
    }
}

// We emit a single, unified representation of a frame, which is what we pass on to users.
#[derive(Debug, Clone, Serialize)]
pub struct Frame {
    pub mangled_name: String,          // Mangled name of the function
    pub line: Option<u32>,             // Line the function is define on, if known
    pub column: Option<u32>,           // Column the function is defined on, if known
    pub source: Option<String>,        // Generally, the file the function is defined in
    pub in_app: bool,                  // We hard-require clients to tell us this?
    pub resolved_name: Option<String>, // The name of the function, after symbolification
    pub lang: String,                  // The language of the frame. Always known (I guess?)
}

impl From<(RawJSFrame, Token<'_>)> for Frame {
    fn from(src: (RawJSFrame, Token)) -> Self {
        let (raw_frame, token) = src;

        Self {
            mangled_name: raw_frame.fn_name,
            line: Some(token.get_src_line()),
            column: Some(token.get_src_col()),
            source: token.get_source().map(String::from),
            in_app: raw_frame.in_app,
            resolved_name: token.get_name().map(String::from),
            lang: "javascript".to_string(),
        }
    }
}
