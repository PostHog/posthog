use std::cmp::min;

use reqwest::Url;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use sourcemap::{SourceMap, Token};

use crate::{
    error::{Error, JsResolveErr, ResolutionError},
    frames::Frame,
    symbol_store::SymbolCatalog,
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

impl RawJSFrame {
    pub async fn resolve<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, Error>
    where
        C: SymbolCatalog<Url, SourceMap>,
    {
        match self.resolve_impl(team_id, catalog).await {
            Ok(frame) => Ok(frame),
            Err(Error::ResolutionError(ResolutionError::JavaScript(e))) => {
                Ok(self.handle_resolution_error(e))
            }
            Err(e) => Err(e),
        }
    }

    async fn resolve_impl<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, Error>
    where
        C: SymbolCatalog<Url, SourceMap>,
    {
        let url = self.source_url()?;

        let sourcemap = catalog.lookup(team_id, url).await?;
        let Some(token) = sourcemap.lookup_token(self.line, self.column) else {
            return Err(
                JsResolveErr::TokenNotFound(self.fn_name.clone(), self.line, self.column).into(),
            );
        };

        Ok(Frame::from((self, token)))
    }

    // JS frames can only handle JS resolution errors - errors at the network level
    pub fn handle_resolution_error(&self, e: JsResolveErr) -> Frame {
        // If we failed to resolve the frame, we mark it as "not resolved" and add the error message,
        // then return a Frame anyway, because frame handling is a best-effort thing.
        (self, e).into()
    }

    pub fn source_url(&self) -> Result<Url, JsResolveErr> {
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

    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        hasher.update(self.fn_name.as_bytes());
        hasher.update(self.line.to_string().as_bytes());
        hasher.update(self.column.to_string().as_bytes());
        hasher.update(
            self.source_url
                .as_ref()
                .unwrap_or(&"".to_string())
                .as_bytes(),
        );
        format!("{:x}", hasher.finalize())
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
            resolved: true,
            resolve_failure: None,
            context: get_context(&token),
        }
    }
}

impl From<(&RawJSFrame, JsResolveErr)> for Frame {
    fn from((raw_frame, err): (&RawJSFrame, JsResolveErr)) -> Self {
        Self {
            mangled_name: raw_frame.fn_name.clone(),
            line: Some(raw_frame.line),
            column: Some(raw_frame.column),
            source: raw_frame.source_url().map(|u| u.path().to_string()).ok(),
            in_app: raw_frame.in_app,
            resolved_name: None,
            lang: "javascript".to_string(),
            resolved: false,
            resolve_failure: Some(err.to_string()),
            context: None,
        }
    }
}

fn get_context(token: &Token) -> Option<String> {
    let sv = token.get_source_view()?;

    let token_line = token.get_src_line();
    let start_line = token_line.saturating_sub(5);
    let end_line = min(token_line.saturating_add(5) as usize, sv.line_count()) as u32;

    // Rough guess on capacity here
    let mut context = String::with_capacity(((end_line - start_line) * 100) as usize);

    for line in start_line..end_line {
        if let Some(l) = sv.get_line(line) {
            context.push_str(l);
            context.push('\n');
        }
    }

    if !context.is_empty() {
        Some(context)
    } else {
        None
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
            frame.source_url().unwrap(),
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
            frame.source_url().unwrap(),
            "http://example.com/path/to/file.js".parse().unwrap()
        );
    }
}
