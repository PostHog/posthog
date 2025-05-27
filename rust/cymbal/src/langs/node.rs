use crate::{
    error::{Error, JsResolveErr, UnhandledError},
    frames::{Context, ContextLine, Frame},
    metric_consts::FRAME_RESOLVED,
    sanitize_string,
    symbol_store::{chunk_id::OrChunkId, sourcemap::OwnedSourceMapCache, SymbolCatalog},
};
use reqwest::Url;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use symbolic::sourcemapcache::{ScopeLookupResult, SourceLocation, SourcePosition};

use super::{
    js::FrameLocation,
    utils::{add_raw_to_junk, get_context},
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawNodeFrame {
    pub filename: String,    // The relative path of the file the context line is in
    pub function: String,    // The name of the function the exception came from
    pub lineno: Option<u32>, // The line number of the context line
    pub colno: Option<u32>,  // The column number of the context line
    pub module: Option<String>, // The python-import style module name the function is in
    // Default to false as sometimes not present on library code
    #[serde(default)]
    pub in_app: bool, // Whether the frame is in the user's code
    pub context_line: Option<String>, // The line of code the exception came from
    #[serde(default)]
    pub pre_context: Vec<String>, // The lines of code before the context line
    #[serde(default)]
    pub post_context: Vec<String>, // The lines of code after the context line
    #[serde(alias = "chunkId", skip_serializing_if = "Option::is_none")]
    pub chunk_id: Option<String>,
}

impl RawNodeFrame {
    pub async fn resolve<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<Url>, OwnedSourceMapCache>,
    {
        let chunk_id = match &self.chunk_id {
            None => return Ok(self.into()),
            Some(chunk_id) => chunk_id.clone(),
        };

        match self.resolve_impl(team_id, catalog, chunk_id).await {
            Ok(frame) => Ok(frame),
            Err(Error::ResolutionError(_)) => Ok(self.into()),
            Err(Error::UnhandledError(e)) => Err(e),
            Err(Error::EventError(_)) => unreachable!(),
        }
    }

    async fn resolve_impl<C>(
        &self,
        team_id: i32,
        catalog: &C,
        chunk_id: String,
    ) -> Result<Frame, Error>
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
                return Ok(Frame::from((self, location)));
            } else {
                return Err(JsResolveErr::TokenNotFound(
                    self.function.clone(),
                    location.line,
                    location.column,
                )
                .into());
            };
        } else {
            return Ok(self.into());
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

    pub fn get_context(&self) -> Option<Context> {
        let context_line = self.context_line.as_ref()?;
        let lineno = self.lineno?;

        let line = ContextLine::new(lineno, context_line);

        let before = self
            .pre_context
            .iter()
            .enumerate()
            .map(|(i, line)| ContextLine::new(lineno - i as u32 - 1, line.clone()))
            .collect();
        let after = self
            .post_context
            .iter()
            .enumerate()
            .map(|(i, line)| ContextLine::new(lineno + i as u32 + 1, line.clone()))
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
            raw_id: String::new(),
            mangled_name: raw.function.clone(),
            line: raw.lineno,
            column: None,
            source: Some(raw.filename.clone()),
            in_app: raw.in_app,
            resolved_name: Some(raw.function.clone()),
            lang: "javascript".to_string(),
            resolved: true,
            resolve_failure: None,
            junk_drawer: None,
            context: raw.get_context(),
        }
    }
}

impl From<(&RawNodeFrame, SourceLocation<'_>)> for Frame {
    fn from((raw_frame, location): (&RawNodeFrame, SourceLocation)) -> Self {
        metrics::counter!(FRAME_RESOLVED, "lang" => "javascript").increment(1);

        let resolved_name = match location.scope() {
            ScopeLookupResult::NamedScope(name) => Some(sanitize_string(name.to_string())),
            ScopeLookupResult::AnonymousScope => Some("<anonymous>".to_string()),
            ScopeLookupResult::Unknown => None,
        };

        let source = location
            .file()
            .and_then(|f| f.name())
            .map(|s| s.to_string());

        let in_app = source
            .map(|s| !s.contains("node_modules"))
            .unwrap_or(raw_frame.in_app);

        let mut res = Self {
            raw_id: String::new(), // We use placeholders here, as they're overriden at the RawFrame level
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
            context: get_context(&location),
        };

        add_raw_to_junk(&mut res, raw_frame);

        res
    }
}
