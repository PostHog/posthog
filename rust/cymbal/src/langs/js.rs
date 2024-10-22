use reqwest::Url;
use serde::{Deserialize, Serialize};
use sourcemap::Token;

use crate::{
    error::{Error, JsResolveErr},
    types::frames::Frame,
};

// A minifed JS stack frame. Just the minimal information needed to lookup some
// sourcemap for it and produce a "real" stack frame.
// TODO - how do we know if this frame is minified? If it isn't, we can skip a lot of work, but I think we have to guess? Based on whether we can get a sourcemap for it?
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawJSFrame {
    #[serde(rename = "lineno")]
    pub line: u32,
    #[serde(rename = "colno")]
    pub column: u32,
    #[serde(rename = "filename")]
    pub source_url: Option<String>, // The url the the script the frame was in was fetched from
    pub in_app: bool,
    #[serde(rename = "function")]
    pub fn_name: String,
}

// export interface StackFrame {
//     filename?: string
//     function?: string
//     module?: string
//     platform?: string
//     lineno?: number
//     colno?: number
//     abs_path?: string
//     context_line?: string
//     pre_context?: string[]
//     post_context?: string[]
//     in_app?: boolean
//     instruction_addr?: string
//     addr_mode?: string
//     vars?: { [key: string]: any }
//     debug_id?: string
// }

impl RawJSFrame {
    pub fn source_ref(&self) -> Result<Url, JsResolveErr> {
        // We can't resolve a frame without a source ref, and are forced
        // to assume this frame is not minified
        let Some(source_url) = &self.source_url else {
            return Err(JsResolveErr::NoSourceUrl);
        };

        // We outright reject relative URLs, or ones that are not HTTP
        if !source_url.starts_with("http://") && !source_url.starts_with("https://") {
            return Err(JsResolveErr::InvalidSourceUrl(source_url.clone()));
        }

        // TODO - we assume these are always absolute urls, and maybe should handle cases where
        // they aren't? We control this on the client side, and I'd prefer to enforce it here.

        // These urls can have a trailing line and column number, formatted like: http://example.com/path/to/file.js:1:2.
        // We need to strip that off to get the actual source url
        // If the last colon is after the last slash, remove it, under the assumption that it's a column number.
        // If there is no colon, or it's before the last slash, we assume the whole thing is a url,
        // with no trailing line and column numbers
        let last_colon = source_url.rfind(':');
        let last_slash = source_url.rfind('/');
        let useful = match (last_colon, last_slash) {
            (Some(colon), Some(slash)) if colon > slash => colon,
            _ => source_url.len(),
        };

        // We do this check one more time, to account for possible line number
        let source_url = &source_url[..useful];
        let last_colon = source_url.rfind(':');
        let last_slash = source_url.rfind('/');
        let useful = match (last_colon, last_slash) {
            (Some(colon), Some(slash)) if colon > slash => colon,
            _ => source_url.len(),
        };

        Url::parse(&source_url[..useful])
            .map_err(|_| JsResolveErr::InvalidSourceUrl(source_url.to_string()))
    }

    // JS frames can only handle JS resolution errors - errors at the network level
    pub fn try_handle_resolution_error(&self, e: JsResolveErr) -> Result<Frame, Error> {
        // A bit naughty, but for code like this, justified I think
        use JsResolveErr::{
            InvalidSourceMap, InvalidSourceMapHeader, InvalidSourceMapUrl, InvalidSourceUrl,
            NoSourceUrl, NoSourcemap, TokenNotFound,
        };

        // I break out all the cases individually here, rather than using an _ to match all,
        // because I want this to stop compiling if we add new cases
        Ok(match e {
            NoSourceUrl => self.try_assume_unminified().ok_or(NoSourceUrl), // We assume we're not minified
            NoSourcemap(u) => self.try_assume_unminified().ok_or(NoSourcemap(u)),
            InvalidSourceMap(e) => Err(JsResolveErr::from(e)),
            TokenNotFound(s, l, c) => Err(TokenNotFound(s, l, c)),
            InvalidSourceUrl(u) => Err(InvalidSourceUrl(u)),
            InvalidSourceMapHeader(u) => Err(InvalidSourceMapHeader(u)),
            InvalidSourceMapUrl(u) => Err(InvalidSourceMapUrl(u)),
        }?)
    }

    // Returns none if the frame is
    fn try_assume_unminified(&self) -> Option<Frame> {
        // TODO - we should include logic here that uses some kind of heuristic to determine
        // if this frame is minified or not. Right now, we simply assume it isn't if this is
        // being called (and all the cases where it's called are above)
        Some(Frame {
            mangled_name: self.fn_name.clone(),
            line: Some(self.line),
            column: Some(self.column),
            source: self.source_url.clone(), // Maybe we have one?
            in_app: self.in_app,
            resolved_name: Some(self.fn_name.clone()), // This is the bit we'd want to check
            lang: "javascript".to_string(),
        })
    }
}

impl From<(&RawJSFrame, Token<'_>)> for Frame {
    fn from(src: (&RawJSFrame, Token)) -> Self {
        let (raw_frame, token) = src;

        Self {
            mangled_name: raw_frame.fn_name.clone(),
            line: Some(token.get_src_line()),
            column: Some(token.get_src_col()),
            source: token.get_source().map(String::from),
            in_app: raw_frame.in_app,
            resolved_name: token.get_name().map(String::from),
            lang: "javascript".to_string(),
        }
    }
}

#[cfg(test)]
mod test {
    #[test]
    fn source_ref_generation() {
        let frame = super::RawJSFrame {
            line: 1,
            column: 2,
            source_url: Some("http://example.com/path/to/file.js:1:2".to_string()),
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
            source_url: Some("http://example.com/path/to/file.js".to_string()),
            in_app: true,
            fn_name: "main".to_string(),
        };

        assert_eq!(
            frame.source_ref().unwrap(),
            "http://example.com/path/to/file.js".parse().unwrap()
        );
    }
}
