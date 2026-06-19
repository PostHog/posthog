use crate::{
    error::{FrameError, JsResolveErr, ResolveError, UnhandledError},
    frames::{record_frame_resolution_failure, Context, ContextLine, Frame},
    langs::CommonFrameMetadata,
    sanitize_string,
    symbolication::symbol_store::{
        chunk_id::OrChunkId, sourcemap::OwnedSourceMapCache, SymbolCatalog,
    },
};
use common_types::error_tracking::FrameId;
use reqwest::Url;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use symbolic::sourcemapcache::{ScopeLookupResult, SourceLocation, SourcePosition};
use tracing::warn;

use super::{
    js::FrameLocation,
    utils::{add_raw_to_junk, get_sourcelocation_context},
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawNodeFrame {
    pub filename: String,    // The relative path of the file the context line is in
    pub function: String,    // The name of the function the exception came from
    pub lineno: Option<u32>, // The line number of the context line
    pub colno: Option<u32>,  // The column number of the context line
    pub module: Option<String>, // The python-import style module name the function is in. TODO - this seems like a copy-paste error?
    pub context_line: Option<String>, // The line of code the exception came from
    #[serde(default)]
    pub pre_context: Vec<String>, // The lines of code before the context line
    #[serde(default)]
    pub post_context: Vec<String>, // The lines of code after the context line
    #[serde(alias = "chunkId", skip_serializing_if = "Option::is_none")]
    pub chunk_id: Option<String>,
    #[serde(flatten)]
    meta: CommonFrameMetadata,
}

impl RawNodeFrame {
    pub async fn resolve_frame<C>(
        &self,
        team_id: i32,
        catalog: &C,
        context_lines: usize,
    ) -> Result<Frame, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<Url>, OwnedSourceMapCache>,
    {
        let Some(chunk_id) = &self.chunk_id else {
            return Ok(self.into());
        };

        match self
            .resolve_impl(team_id, catalog, chunk_id.clone(), context_lines)
            .await
        {
            Ok(frame) => Ok(frame),
            Err(ResolveError::ResolutionError(FrameError::JavaScript(e))) => Ok((self, e).into()),
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => {
                Ok((self, JsResolveErr::NoSourcemapUploaded(chunk_id)).into())
            }
            Err(ResolveError::ResolutionError(e)) => {
                warn!("Unexpected Node.js symbol resolution error: {:?}", e);
                Ok((self, JsResolveErr::InvalidSourceMap(e.to_string())).into())
            }
            Err(ResolveError::UnhandledError(e)) => Err(e),
        }
    }

    async fn resolve_impl<C>(
        &self,
        team_id: i32,
        catalog: &C,
        chunk_id: String,
        context_lines: usize,
    ) -> Result<Frame, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<Url>, OwnedSourceMapCache>,
    {
        if let Some(location) = self.get_location() {
            // We need a chunk ID to resolve a frame
            let chunk_ref = OrChunkId::ChunkId(chunk_id);
            let sourcemap = catalog.lookup(team_id, chunk_ref).await?;
            let smc = sourcemap.get_smc();
            // Note: javascript stack frame lines are 1-indexed, so we have to subtract 1
            if let Some(location) =
                smc.lookup(SourcePosition::new(location.line - 1, location.column))
            {
                Ok(Frame::from((self, location, context_lines)))
            } else {
                Err(JsResolveErr::TokenNotFound(
                    self.function.clone(),
                    location.line,
                    location.column,
                )
                .into())
            }
        } else {
            Ok(self.into())
        }
    }

    pub fn get_location(&self) -> Option<FrameLocation> {
        if let (Some(lineno), Some(colno)) = (self.lineno, self.colno) {
            Some(FrameLocation {
                line: lineno,
                column: colno,
            })
        } else {
            None
        }
    }

    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        self.context_line
            .as_ref()
            .inspect(|c| hasher.update(c.as_bytes()));
        hasher.update(self.filename.as_bytes());
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        self.module
            .as_ref()
            .inspect(|m| hasher.update(m.as_bytes()));
        self.pre_context
            .iter()
            .chain(self.post_context.iter())
            .for_each(|line| {
                hasher.update(line.as_bytes());
            });
        format!("{:x}", hasher.finalize())
    }

    // Clients compute in_app from their local layout (and default to true when
    // unsure), so identical stacks arrive with different in_app masks depending
    // on the host they were captured on. Fingerprinting selects frames by in_app,
    // so each mask would mint a new fingerprint for the same crash. Demote frames
    // that are clearly dependency or runtime code; we never promote, so an explicit
    // client in_app=false still wins. Mirrors the node_modules check already applied
    // on the sourcemap-resolved path, extending it to the unresolved frame paths.
    pub fn in_app(&self) -> bool {
        self.meta.in_app && !is_dependency_source(&self.filename)
    }

    pub fn get_context(&self) -> Option<Context> {
        let context_line = self.context_line.as_ref()?;
        let lineno = self.lineno?;

        let line = ContextLine::new(lineno, context_line);

        let before = self
            .pre_context
            .iter()
            .rev()
            .enumerate()
            .map(|(i, line)| ContextLine::new_rel(lineno, -(i as i32) - 1, line.clone()))
            .collect();
        let after = self
            .post_context
            .iter()
            .enumerate()
            .map(|(i, line)| ContextLine::new_rel(lineno, (i as i32) + 1, line.clone()))
            .collect();
        Some(Context {
            before,
            line,
            after,
        })
    }
}

impl From<&RawNodeFrame> for Frame {
    fn from(raw: &RawNodeFrame) -> Self {
        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno,
            column: None,
            source: Some(raw.filename.clone()),
            in_app: raw.in_app(),
            resolved_name: Some(raw.function.clone()),
            lang: "javascript".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            context: raw.get_context(),
            release: None,
            synthetic: raw.meta.synthetic,
            suspicious: false,
            module: raw.module.clone(),
            code_variables: None,
        }
    }
}

impl From<(&RawNodeFrame, SourceLocation<'_>, usize)> for Frame {
    fn from((raw_frame, location, context_lines): (&RawNodeFrame, SourceLocation, usize)) -> Self {
        let resolved_name = match location.scope() {
            ScopeLookupResult::NamedScope(name) => Some(sanitize_string(name.to_string())),
            ScopeLookupResult::AnonymousScope => Some("<anonymous>".to_string()),
            ScopeLookupResult::Unknown => None,
        };

        let source = location
            .file()
            .and_then(|f| f.name())
            .map(|s| s.to_string());

        // Demote-only, consistent with the unresolved paths: honor an explicit
        // client in_app=false rather than promoting it back to true on resolution.
        // Base on raw_frame.in_app() so the raw filename is still checked when the
        // resolved source has no name.
        let in_app = raw_frame.in_app() && !source.as_deref().is_some_and(is_dependency_source);

        let mut res = Self {
            frame_id: FrameId::placeholder(),
            mangled_name: raw_frame.function.clone(),
            line: Some(location.line()),
            column: Some(location.column()),
            source: location
                .file()
                .and_then(|f| f.name())
                .map(|s| sanitize_string(s.to_string())),
            in_app,
            resolved_name,
            lang: "javascript".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            code_variables: None,
            context: get_sourcelocation_context(&location, context_lines),
            release: None,
            synthetic: raw_frame.meta.synthetic,
            suspicious: false,
            module: raw_frame.module.clone(),
        };

        add_raw_to_junk(&mut res, raw_frame);

        res
    }
}

impl From<(&RawNodeFrame, JsResolveErr)> for Frame {
    fn from((raw_frame, resolve_err): (&RawNodeFrame, JsResolveErr)) -> Self {
        let was_minified = raw_frame
            .get_context()
            .as_ref()
            .map(context_likely_minified)
            .unwrap_or_default();

        let resolved = !was_minified;

        // Only record a frame-resolution-failure when the frame is actually unresolved —
        // when context heuristics say "not minified", the dispatcher emits `FRAME_RESOLVED`
        // and firing here too would double-count.
        if !resolved {
            record_frame_resolution_failure(
                "javascript",
                resolve_err.metric_reason(),
                &resolve_err,
            );
        }

        let resolved_name = if was_minified {
            None
        } else {
            Some(raw_frame.function.clone())
        };

        let resolve_failure = Some(resolve_err.to_string());

        let mut res = Self {
            frame_id: FrameId::placeholder(),
            mangled_name: raw_frame.function.clone(),
            line: raw_frame.lineno,
            column: raw_frame.colno,
            source: None,
            in_app: raw_frame.in_app(),
            resolved_name,
            lang: "javascript".to_string(),
            resolved,
            // Regardless of whather we think this was a minified frame or not, we still put
            // the error message in resolve_failure, so if a user comes along and want to know
            // why we thought a frame wasn't minified, they can see the error message
            resolve_failure,
            junk_drawer: None,
            code_variables: None,
            context: raw_frame.get_context(),
            release: None,
            synthetic: raw_frame.meta.synthetic,
            suspicious: false,
            module: raw_frame.module.clone(),
        };

        add_raw_to_junk(&mut res, raw_frame);

        res
    }
}

fn context_likely_minified(ctx: &Context) -> bool {
    let avg_len = ctx
        .before
        .iter()
        .chain(ctx.after.iter())
        .map(|line| line.line.len())
        .sum::<usize>() as f64
        / (ctx.before.len() + ctx.after.len()) as f64;
    avg_len > 300.0
}

// Source markers that identify non-application Node code: installed dependencies
// (node_modules) and Node's built-in modules (the `node:` scheme, e.g. `node:fs`).
fn is_dependency_source(source: &str) -> bool {
    source.contains("node_modules") || source.starts_with("node:")
}

#[cfg(test)]
mod test {
    use super::RawNodeFrame;

    #[test]
    fn test_in_app_normalization() {
        let cases = [
            (
                "node_modules frames are demoted",
                serde_json::json!({
                    "filename": "/app/node_modules/express/lib/router/index.js",
                    "function": "handle",
                    "in_app": true,
                }),
                false,
            ),
            (
                "node builtin modules are demoted",
                serde_json::json!({
                    "filename": "node:internal/process/task_queues",
                    "function": "processTicksAndRejections",
                    "in_app": true,
                }),
                false,
            ),
            (
                "unset in_app defaults true but dependency code is still demoted",
                serde_json::json!({
                    "filename": "/app/node_modules/pg/lib/client.js",
                    "function": "query",
                }),
                false,
            ),
            (
                "application frames stay in_app",
                serde_json::json!({
                    "filename": "/app/src/handlers/user.js",
                    "function": "getUser",
                    "in_app": true,
                }),
                true,
            ),
            (
                "application frame with no in_app field defaults to true",
                serde_json::json!({
                    "filename": "/app/src/index.js",
                    "function": "main",
                }),
                true,
            ),
            (
                "explicit client false is never promoted",
                serde_json::json!({
                    "filename": "/app/src/handlers/user.js",
                    "function": "getUser",
                    "in_app": false,
                }),
                false,
            ),
        ];

        for (case, value, expected) in cases {
            let raw: RawNodeFrame = serde_json::from_value(value).unwrap();
            assert_eq!(raw.in_app(), expected, "{case}");
        }
    }
}
