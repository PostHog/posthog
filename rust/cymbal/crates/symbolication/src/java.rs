use std::sync::Arc;

use common_types::error_tracking::FrameId;
use proguard::StackFrame;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use tracing::warn;

use crate::{
    record_frame_resolution_failure, utils::add_raw_to_junk, CommonFrameMetadata, Frame, IntoFrame,
    SymbolCatalog,
};
use cymbal_symbol_store::{
    chunk_id::OrChunkId,
    proguard::{FetchedMapping, ProguardRef},
    FrameError, ProguardError, ResolveError, UnhandledError,
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawJavaFrame {
    pub filename: Option<String>, // The relative path of the file the context line is in
    pub function: String,         // The name of the function the exception came from
    pub lineno: Option<usize>,    // The line number of the context line
    pub module: String,           // The java-import style module name the function is in
    pub map_id: Option<String>, // ID of the proguard mapping symbol set this frame can be demangled with
    #[serde(default)]
    // Java compilers sometimes generate synthetic methods, for stuff like implied accessors from the source
    // More info at https://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html#jvms-4.7.8
    //
    // TODO - we've used "synthetic" to mean "constructed by our SDK". This is a language-specific
    // meaning, and I'm not sure how to use it in our app. I'm also not /sure/ it matters, though.
    pub method_synthetic: bool,
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

    pub async fn resolve<C>(&self, team_id: i32, catalog: &C) -> Result<Vec<Frame>, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        match self.resolve_impl(team_id, catalog).await {
            Ok(frames) => Ok(frames),
            Err(ResolveError::ResolutionError(FrameError::Proguard(e))) => {
                Ok(vec![self.handle_resolution_error(e)])
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => Ok(
                vec![self.handle_resolution_error(ProguardError::MissingMap(chunk_id))],
            ),
            Err(ResolveError::ResolutionError(e)) => {
                warn!("Unexpected Proguard symbol resolution error: {:?}", e);
                Ok(vec![
                    self.handle_resolution_error(ProguardError::InvalidMapping)
                ])
            }
            Err(ResolveError::UnhandledError(e)) => Err(e),
        }
    }

    async fn resolve_impl<C>(&self, team_id: i32, catalog: &C) -> Result<Vec<Frame>, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        let r = self.get_ref()?;
        let map: Arc<FetchedMapping> = catalog.lookup(team_id, r.clone()).await?;
        let cache = map.get_cache()?;

        let frame = match self.filename.as_ref() {
            Some(file) => StackFrame::with_file(
                &self.module,
                &self.function,
                self.lineno.unwrap_or_default(),
                file,
            ),
            None => StackFrame::new(
                &self.module,
                &self.function,
                self.lineno.unwrap_or_default(),
            ),
        };

        let res: Vec<Frame> = cache
            .remap_frame(&frame)
            .map(|re| (self, re).into_frame())
            .collect();

        if res.is_empty() {
            warn!(
                "Failed to construct any remapped frames from the raw frame {} and chunk id {}",
                self.frame_id(),
                self.get_ref()?
            );
            Ok(vec![(self, ProguardError::NoOriginalFrames).into_frame()])
        } else {
            Ok(res)
        }
    }

    pub fn handle_resolution_error(&self, error: ProguardError) -> Frame {
        (self, error).into_frame()
    }

    pub fn symbol_set_ref(&self) -> Option<String> {
        self.get_ref().ok().map(|r| r.to_string())
    }

    pub fn get_ref(&self) -> Result<OrChunkId<ProguardRef>, ProguardError> {
        self.map_id
            .as_ref()
            .map(|id| OrChunkId::chunk_id(id.clone()))
            .ok_or(ProguardError::NoMapId)
    }

    pub async fn remap_class<C>(
        &self,
        team_id: i32,
        class: &str,
        catalog: &C,
    ) -> Result<Option<String>, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping>,
    {
        let r = self.get_ref()?;
        let map: Arc<FetchedMapping> = catalog.lookup(team_id, r.clone()).await?;
        Ok(map.remap_class(class)?)
    }
}

impl<'a> IntoFrame for (&'a RawJavaFrame, StackFrame<'a>) {
    fn into_frame(self) -> Frame {
        let (raw, remapped) = self;
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: Some(remapped.line() as u32),
            column: None,
            source: remapped.file().map(ToString::to_string),
            in_app: raw.meta.in_app,
            resolved_name: Some(remapped.method().to_string()),
            lang: "java".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            code_variables: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(remapped.class().to_string()),
        };

        add_raw_to_junk(&mut f, raw);

        f
    }
}

impl IntoFrame for (&RawJavaFrame, ProguardError) {
    fn into_frame(self) -> Frame {
        let (raw, error) = self;
        record_frame_resolution_failure("java", error.metric_reason(), &error);

        let resolve_failure = Some(error.to_string());

        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno.map(|ln| ln as u32),
            column: None,
            source: raw.filename.clone(),
            in_app: raw.meta.in_app,
            resolved_name: None,
            lang: "java".to_string(),
            resolved: false,
            resolve_failure,
            junk_drawer: None,
            code_variables: None,
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

#[cfg(test)]
mod tests {
    use super::*;

    fn make_raw_no_map() -> RawJavaFrame {
        RawJavaFrame {
            filename: Some("UserService.java".to_string()),
            function: "getUser".to_string(),
            lineno: Some(88),
            module: "com.example.UserService".to_string(),
            map_id: None, // no map_id → ProguardError::NoMapId
            method_synthetic: false,
            meta: CommonFrameMetadata {
                in_app: true,
                synthetic: false,
            },
        }
    }

    #[test]
    fn handle_resolution_error_no_map_id() {
        let raw = make_raw_no_map();
        let frame = raw.handle_resolution_error(ProguardError::NoMapId);

        assert!(!frame.resolved);
        assert!(frame.resolve_failure.is_some());
        assert!(frame
            .resolve_failure
            .as_ref()
            .unwrap()
            .contains("No map ID"));
        assert_eq!(frame.lang, "java");
        assert_eq!(frame.mangled_name, "getUser");
        assert_eq!(frame.module, Some("com.example.UserService".to_string()));
    }

    #[test]
    fn handle_resolution_error_missing_map() {
        let raw = make_raw_no_map();
        let frame = raw.handle_resolution_error(ProguardError::MissingMap("abc123".to_string()));

        assert!(!frame.resolved);
        let failure = frame.resolve_failure.as_ref().unwrap();
        assert!(failure.contains("abc123"));
    }

    #[test]
    fn symbol_set_ref_present_when_map_id_set() {
        let mut raw = make_raw_no_map();
        raw.map_id = Some("map-abc".to_string());
        assert_eq!(raw.symbol_set_ref(), Some("map-abc".to_string()));
    }

    #[test]
    fn symbol_set_ref_none_when_no_map_id() {
        let raw = make_raw_no_map();
        assert!(raw.symbol_set_ref().is_none());
    }

    #[test]
    fn frame_id_stable_java() {
        let raw = make_raw_no_map();
        assert_eq!(raw.frame_id(), raw.frame_id());
    }
}
