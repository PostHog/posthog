use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    error::{FrameError, ProguardError, ResolveError, UnhandledError},
    frames::Frame,
    langs::{utils::add_raw_to_junk, CommonFrameMetadata},
    symbol_store::{
        chunk_id::OrChunkId,
        proguard::{FetchedMapping, ProguardRef},
        SymbolCatalog,
    },
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawJavaFrame {
    pub filename: Option<String>, // The relative path of the file the context line is in
    pub function: String,         // The name of the function the exception came from
    pub lineno: Option<u32>,      // The line number of the context line
    pub module: String,           // The java-import style module name the function is in
    pub map_id: Option<String>, // ID of the proguard mapping symbol set this frame can be demangled with
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawJavaFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for java frames, so we rely on
        // the module, function and line number to
        // uniquely identify a frame, with the intuition being that even
        // if two frames are from two different library versions, if the
        // files they're in are sufficiently similar we can consider
        // them to be the same frame
        let mut hasher = Sha512::new();
        if let Some(filename) = &self.filename {
            hasher.update(filename.as_bytes());
        }
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.module.as_bytes());
        format!("{:x}", hasher.finalize())
    }

    pub async fn resolve<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        match self.resolve_impl(team_id, catalog).await {
            Ok(frame) => Ok(frame),
            Err(ResolveError::ResolutionError(FrameError::Proguard(e))) => {
                Ok(self.handle_resolution_error(e))
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => {
                Ok(self.handle_resolution_error(ProguardError::MissingMap(chunk_id)))
            }
            Err(ResolveError::ResolutionError(e)) => {
                // TODO - other kinds of errors here should be unreachable, we need to specialize ResolveError to encode that
                unreachable!("Should not have received error {:?}", e)
            }
            Err(ResolveError::UnhandledError(e)) => Err(e),
        }
    }

    async fn resolve_impl<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        let r = self.get_ref()?;
        let map = catalog.lookup(team_id, r.clone()).await?;

        todo!()
    }

    pub fn handle_resolution_error(&self, error: ProguardError) -> Frame {
        (self, error).into()
    }

    pub fn symbol_set_ref(&self) -> Option<String> {
        self.get_ref().ok().map(|r| r.to_string())
    }

    fn get_ref(&self) -> Result<OrChunkId<ProguardRef>, ProguardError> {
        self.map_id
            .as_ref()
            .map(|id| OrChunkId::chunk_id(id.clone()))
            .ok_or(ProguardError::NoMapId)
    }
}

impl From<(&RawJavaFrame, ProguardError)> for Frame {
    fn from((raw, error): (&RawJavaFrame, ProguardError)) -> Self {
        let mut f = Frame {
            raw_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno,
            column: None,
            source: raw.filename.clone(),
            in_app: raw.meta.in_app,
            resolved_name: None,
            lang: "java".to_string(),
            resolved: false,
            resolve_failure: Some(error.to_string()),
            junk_drawer: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(raw.module.clone()),
        };

        add_raw_to_junk(&mut f, raw);

        f
    }
}
