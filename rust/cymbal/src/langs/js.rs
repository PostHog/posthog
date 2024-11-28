use std::sync::atomic::Ordering;

use reqwest::Url;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use symbolic::sourcemapcache::{ScopeLookupResult, SourceLocation, SourcePosition};

use crate::{
    config::FRAME_CONTEXT_LINES,
    error::{Error, FrameError, JsResolveErr, UnhandledError},
    frames::{Context, ContextLine, Frame},
    metric_consts::{FRAME_NOT_RESOLVED, FRAME_RESOLVED},
    symbol_store::{sourcemap::OwnedSourceMapCache, SymbolCatalog},
};

// A minifed JS stack frame. Just the minimal information needed to lookup some
// sourcemap for it and produce a "real" stack frame.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawJSFrame {
    #[serde(flatten)]
    pub location: Option<FrameLocation>, // Sometimes we get frames with no location information. We treat these as already resolved, or unminified
    #[serde(rename = "filename")]
    pub source_url: Option<String>, // The url the the script the frame was in was fetched from
    pub in_app: bool,
    #[serde(rename = "function")]
    pub fn_name: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, Eq, PartialEq)]
pub struct FrameLocation {
    #[serde(rename = "lineno")]
    pub line: u32,
    #[serde(rename = "colno")]
    pub column: u32,
}

impl RawJSFrame {
    pub async fn resolve<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, UnhandledError>
    where
        C: SymbolCatalog<Url, OwnedSourceMapCache>,
    {
        match self.resolve_impl(team_id, catalog).await {
            Ok(frame) => Ok(frame),
            Err(Error::ResolutionError(FrameError::JavaScript(e))) => {
                Ok(self.handle_resolution_error(e))
            }
            Err(Error::UnhandledError(e)) => Err(e),
        }
    }

    async fn resolve_impl<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, Error>
    where
        C: SymbolCatalog<Url, OwnedSourceMapCache>,
    {
        let url = self.source_url()?;

        let Some(location) = &self.location else {
            return Ok(Frame::from(self)); // We're probably an unminified frame
        };

        let sourcemap = catalog.lookup(team_id, url).await?;

        let smc = sourcemap.get_smc();

        // Note: javascript stack frame lines are 1-indexed, so we have to subtract 1
        let Some(location) = smc.lookup(SourcePosition::new(location.line - 1, location.column))
        else {
            return Err(JsResolveErr::TokenNotFound(
                self.fn_name.clone(),
                location.line,
                location.column,
            )
            .into());
        };

        Ok(Frame::from((self, location)))
    }

    // JS frames can only handle JS resolution errors - errors at the network level
    pub fn handle_resolution_error(&self, e: JsResolveErr) -> Frame {
        // If we failed to resolve the frame, we mark it as "not resolved" and add the error message,
        // then return a Frame anyway, because frame handling is a best-effort thing.
        let Some(location) = &self.location else {
            return self.into();
        };
        (self, e, location).into()
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
        if let Some(location) = &self.location {
            hasher.update(location.line.to_string().as_bytes());
            hasher.update(location.column.to_string().as_bytes());
        }
        hasher.update(
            self.source_url
                .as_ref()
                .unwrap_or(&"".to_string())
                .as_bytes(),
        );
        format!("{:x}", hasher.finalize())
    }
}

impl From<(&RawJSFrame, SourceLocation<'_>)> for Frame {
    fn from(src: (&RawJSFrame, SourceLocation)) -> Self {
        let (raw_frame, token) = src;
        metrics::counter!(FRAME_RESOLVED, "lang" => "javascript").increment(1);

        let resolved_name = match token.scope() {
            ScopeLookupResult::NamedScope(name) => Some(name.to_string()),
            ScopeLookupResult::AnonymousScope => Some("<anonymous>".to_string()),
            ScopeLookupResult::Unknown => None,
        };

        let source = token.file().and_then(|f| f.name()).map(|s| s.to_string());

        let in_app = source
            .map(|s| !s.contains("node_modules"))
            .unwrap_or(raw_frame.in_app);

        let mut res = Self {
            raw_id: String::new(), // We use placeholders here, as they're overriden at the RawFrame level
            mangled_name: raw_frame.fn_name.clone(),
            line: Some(token.line()),
            column: Some(token.column()),
            source: token.file().and_then(|f| f.name()).map(|s| s.to_string()),
            in_app,
            resolved_name,
            lang: "javascript".to_string(),
            resolved: true,
            resolve_failure: None,
            junk_drawer: None,
            context: get_context(&token),
        };

        add_raw_to_junk(&mut res, raw_frame);

        res
    }
}

// If we failed to resolve the frame, but it's a frame that has location information,
// mark it as a failed resolve and emit an "unresolved" frame
impl From<(&RawJSFrame, JsResolveErr, &FrameLocation)> for Frame {
    fn from((raw_frame, err, location): (&RawJSFrame, JsResolveErr, &FrameLocation)) -> Self {
        metrics::counter!(FRAME_NOT_RESOLVED, "lang" => "javascript").increment(1);

        // TODO - extremely rough
        let was_minified = match err {
            JsResolveErr::NoSourceUrl => false, // This frame's `source` was None
            JsResolveErr::NoSourcemap(_) => false, // A total guess
            _ => true,
        };

        let resolved_name = if was_minified {
            None
        } else {
            Some(raw_frame.fn_name.clone())
        };

        let mut res = Self {
            raw_id: String::new(),
            mangled_name: raw_frame.fn_name.clone(),
            line: Some(location.line),
            column: Some(location.column),
            source: raw_frame.source_url().map(|u| u.path().to_string()).ok(),
            in_app: raw_frame.in_app,
            resolved_name,
            lang: "javascript".to_string(),
            resolved: !was_minified,
            // Regardless of whather we think this was a minified frame or not, we still put
            // the error message in resolve_failure, so if a user comes along and want to know
            // why we thought a frame wasn't minified, they can see the error message
            resolve_failure: Some(err.to_string()),
            junk_drawer: None,
            context: None,
        };

        add_raw_to_junk(&mut res, raw_frame);

        res
    }
}

// Finally, if we have a frame that has NO location information, we treat it as not minified, since it's
// probably a native function or something else weird
impl From<&RawJSFrame> for Frame {
    fn from(raw_frame: &RawJSFrame) -> Self {
        metrics::counter!(FRAME_NOT_RESOLVED, "lang" => "javascript").increment(1);
        let mut res = Self {
            raw_id: String::new(),
            mangled_name: raw_frame.fn_name.clone(),
            line: None,
            column: None,
            source: raw_frame.source_url().map(|u| u.path().to_string()).ok(),
            in_app: raw_frame.in_app,
            resolved_name: Some(raw_frame.fn_name.clone()),
            lang: "javascript".to_string(),
            resolved: true, // Without location information, we're assuming this is not minified
            resolve_failure: None,
            junk_drawer: None,
            context: None,
        };

        add_raw_to_junk(&mut res, raw_frame);

        res
    }
}

fn add_raw_to_junk(frame: &mut Frame, raw: &RawJSFrame) {
    // UNWRAP: raw JS frames are definitely representable as json
    frame.add_junk("raw_frame", raw.clone()).unwrap();
}

fn get_context(token: &SourceLocation) -> Option<Context> {
    let file = token.file()?;
    let token_line_num = token.line();
    let src = file.source()?;

    let line_limit = FRAME_CONTEXT_LINES.load(Ordering::Relaxed);
    get_context_lines(src, token_line_num as usize, line_limit)
}

fn get_context_lines(src: &str, line: usize, context_len: usize) -> Option<Context> {
    let start = line.saturating_sub(context_len).saturating_sub(1);

    let mut lines = src.lines().enumerate().skip(start);
    let before = (&mut lines)
        .take(line - start)
        .map(|(number, line)| ContextLine::new(number as u32, line))
        .collect();

    let line = lines
        .next()
        .map(|(number, line)| ContextLine::new(number as u32, line))?;

    let after = lines
        .take(context_len)
        .map(|(number, line)| ContextLine::new(number as u32, line))
        .collect();

    Some(Context {
        before,
        line,
        after,
    })
}

#[cfg(test)]
mod test {
    #[test]
    fn source_ref_generation() {
        let frame = super::RawJSFrame {
            location: None,
            source_url: Some("http://example.com/path/to/file.js:1:2".to_string()),
            in_app: true,
            fn_name: "main".to_string(),
        };

        assert_eq!(
            frame.source_url().unwrap(),
            "http://example.com/path/to/file.js".parse().unwrap()
        );

        let frame = super::RawJSFrame {
            location: None,
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
