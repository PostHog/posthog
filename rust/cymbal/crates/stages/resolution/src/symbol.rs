use async_trait::async_trait;
use cymbal_symbol_store::{
    chunk_id::OrChunkId, proguard::ProguardRef, JsResolveErr, ProguardError, ResolveError,
    UnhandledError,
};
use cymbal_symbolication::{apple::AppleDebugImage, Frame, RawFrame};
use tracing::warn;

use crate::exception::ResolutionException;

const JAVA_EXCEPTION_REMAP_FAILED: &str = "cymbal_java_exception_remap_failed";

#[async_trait]
pub trait SymbolResolver: Send + Sync + 'static {
    async fn resolve_raw_frame(
        &self,
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[AppleDebugImage],
    ) -> Result<Vec<Frame>, UnhandledError>;

    async fn resolve_java_class(
        &self,
        team_id: i32,
        symbolset_ref: OrChunkId<ProguardRef>,
        class: String,
    ) -> Result<String, ResolveError>;

    async fn resolve_dart_minified_name(
        &self,
        team_id: i32,
        symbolset_ref: String,
        minified_name: &str,
    ) -> Result<String, ResolveError>;

    async fn resolve_java_exception(
        &self,
        team_id: i32,
        mut exception: ResolutionException,
    ) -> Result<ResolutionException, UnhandledError> {
        let resolve_java_module_and_type =
            async |exception: &ResolutionException| -> Result<(String, String), ResolveError> {
                if let Some(RawFrame::Java(java_frame)) = exception.first_raw_frame() {
                    let module = exception
                        .module
                        .clone()
                        .ok_or(ProguardError::NoModuleProvided)
                        .map_err(ResolveError::from)?;

                    let class = format!("{}.{}", module, exception.exception_type);
                    let symbolset_ref = java_frame.get_ref()?;

                    let new_class = self
                        .resolve_java_class(team_id, symbolset_ref, class)
                        .await?;

                    let (new_module, new_type) = split_last_dot(new_class.as_str())?;
                    Ok((new_module, new_type))
                } else {
                    Err(ProguardError::NoOriginalFrames.into())
                }
            };

        match resolve_java_module_and_type(&exception).await {
            Ok((new_module, new_type)) => {
                exception.module = Some(new_module);
                exception.exception_type = new_type;
            }
            Err(ResolveError::ResolutionError(frame_error)) => {
                warn!(
                    "Failed to resolve Java exception module and type: {}",
                    frame_error
                );
                metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => frame_error.to_string())
                    .increment(1);
            }
            Err(ResolveError::UnhandledError(err)) => return Err(err),
        };

        Ok(exception)
    }

    async fn resolve_dart_exception(
        &self,
        team_id: i32,
        exception: ResolutionException,
    ) -> Result<ResolutionException, UnhandledError> {
        let chunk_id = exception.raw_frames().iter().find_map(|frame| match frame {
            RawFrame::JavaScriptWeb(js_frame) => js_frame.chunk_id.clone(),
            RawFrame::JavaScriptNode(node_frame) => node_frame.chunk_id.clone(),
            RawFrame::JavaScriptPlatformAlias(js_frame) => js_frame.chunk_id.clone(),
            _ => None,
        });

        let Some(chunk_id) = chunk_id else {
            return Ok(exception);
        };

        match self
            .resolve_dart_minified_name(team_id, chunk_id, &exception.exception_type)
            .await
        {
            Ok(new_type) => {
                let mut new_exception = exception.clone();
                new_exception.exception_type = new_type;
                Ok(new_exception)
            }
            Err(ResolveError::ResolutionError(_)) => Ok(exception),
            Err(ResolveError::UnhandledError(err)) => Err(err),
        }
    }
}

fn split_last_dot(s: &str) -> Result<(String, String), ResolveError> {
    let mut parts = s.rsplitn(2, '.');
    let last = parts
        .next()
        .expect("rsplitn always yields at least one part");
    let before = parts.next().ok_or(ProguardError::InvalidClass)?;
    Ok((before.to_string(), last.to_string()))
}

#[derive(Debug, Default)]
pub struct NoopSymbolResolver;

#[async_trait]
impl SymbolResolver for NoopSymbolResolver {
    async fn resolve_raw_frame(
        &self,
        _team_id: i32,
        frame: &RawFrame,
        _debug_images: &[AppleDebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        Ok(vec![frame.to_unresolved_frame()])
    }

    async fn resolve_java_class(
        &self,
        _team_id: i32,
        _symbolset_ref: OrChunkId<ProguardRef>,
        _class: String,
    ) -> Result<String, ResolveError> {
        Err(ProguardError::MissingClass.into())
    }

    async fn resolve_dart_minified_name(
        &self,
        _team_id: i32,
        _symbolset_ref: String,
        _minified_name: &str,
    ) -> Result<String, ResolveError> {
        Err(JsResolveErr::InvalidSourceAndMap.into())
    }
}

trait RawFrameFallback {
    fn to_unresolved_frame(&self) -> Frame;
}

impl RawFrameFallback for RawFrame {
    fn to_unresolved_frame(&self) -> Frame {
        use cymbal_symbolication::IntoFrame;

        match self {
            RawFrame::Python(frame) => frame.into_frame(),
            RawFrame::Ruby(frame) => frame.into_frame(),
            RawFrame::JavaScriptWeb(frame) | RawFrame::JavaScriptPlatformAlias(frame) => {
                frame.into_frame()
            }
            RawFrame::JavaScriptNode(frame) => frame.into_frame(),
            RawFrame::Go(frame) => frame.into_frame(),
            RawFrame::Php(frame) => frame.into_frame(),
            RawFrame::Hermes(frame) => frame.into_frame(),
            RawFrame::Java(frame) => frame.handle_resolution_error(ProguardError::MissingClass),
            RawFrame::Dart(frame) => frame.into_frame(),
            RawFrame::Apple(frame) => frame.into_frame(),
            RawFrame::Custom(frame) => frame.into_frame(),
        }
    }
}
