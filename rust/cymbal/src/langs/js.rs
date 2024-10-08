use reqwest::Url;
use serde::Deserialize;

use crate::error::Error;

// A minifed JS stack frame. Just the minimal information needed to lookup some
// sourcemap for it and produce a "real" stack frame.
// TODO - how do we know if this frame is minified? If it isn't, we can skip a lot of work, but I think we have to guess? Based on whether we can get a sourcemap for it?
#[derive(Debug, Clone, Deserialize)]
pub struct RawJSFrame {
    #[serde(rename = "lineno")]
    pub line: u32,
    #[serde(rename = "colno")]
    pub column: u32,
    #[serde(rename = "filename")]
    pub script_url: String,
    pub in_app: bool,
    #[serde(rename = "function")]
    pub fn_name: String,
}

impl RawJSFrame {
    pub fn source_ref(&self) -> Result<Url, Error> {
        // Frame scrupt URLs are in the form: `<protocol>://<domain>/<path>:<line>:<column>`. We
        // want to strip the line and column, if they're present, and then return the rest
        let to_protocol_end = self
            .script_url
            .find("://")
            .ok_or(Error::InvalidSourceRef(self.script_url.clone()))?
            + 3;

        let (protocol, rest) = self.script_url.split_at(to_protocol_end);
        let to_end_of_path = rest.find(':').unwrap_or(rest.len());
        let useful = protocol.len() + to_end_of_path;
        let url = &self.script_url[..useful];
        Url::parse(url).map_err(|_| Error::InvalidSourceRef(self.script_url.clone()))
    }
}

#[cfg(test)]
mod test {
    #[test]
    fn source_ref_generation() {
        let frame = super::RawJSFrame {
            line: 1,
            column: 2,
            script_url: "http://example.com/path/to/file.js:1:2".to_string(),
            in_app: true,
            fn_name: "main".to_string(),
        };

        assert_eq!(
            frame.source_ref().unwrap(),
            "http://example.com/path/to/file.js".parse().unwrap()
        );

        let frame = super::RawJSFrame {
            line: 1,
            column: 2,
            script_url: "http://example.com/path/to/file.js".to_string(),
            in_app: true,
            fn_name: "main".to_string(),
        };

        assert_eq!(
            frame.source_ref().unwrap(),
            "http://example.com/path/to/file.js".parse().unwrap()
        );
    }
}
