use serde::{Deserialize, Serialize};

use crate::langs::js::RawJSFrame;

// We consume a huge variety of differently shaped stack frames, which we have special-case
// transformation for, to produce a single, unified representation of a frame.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub enum RawFrame {
    JavaScript(RawJSFrame),
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
