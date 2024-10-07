use serde::Deserialize;

use crate::error::Error;

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

impl RawJSFrame {
    pub fn source_ref(&self) -> Result<String, Error> {
        let chunk = self
            .uri
            .split('/')
            .rev()
            .next()
            .ok_or_else(|| Error::NoSourceRef(self.uri.clone()))?;

        let chunk = chunk
            .split(':')
            .next()
            .ok_or_else(|| Error::NoSourceRef(self.uri.clone()))?;

        Ok(format!("{}.map", chunk))
    }
}
