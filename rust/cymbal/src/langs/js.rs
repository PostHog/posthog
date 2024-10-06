use serde::{Deserialize, Serialize};

// A minifed JS stack frame. Just the minimal information needed to lookup some
// sourcemap for it and produce a "real" stack frame.
#[derive(Debug, Clone, Deserialize)]
pub struct RawJSFrame {
    #[serde(rename = "lineno")]
    pub line: u32,
    #[serde(rename = "colno")]
    pub column: u32,
    #[serde(rename = "filename")]
    pub uri: String,
    pub in_app: bool,
    #[serde(rename = "function")]
    pub fn_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProcessedFrame {
    pub line: u32,
    pub column: u32,
    pub uri: String,
    pub in_app: bool,
    pub fn_name: String,
}
