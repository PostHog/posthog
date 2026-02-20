use axum::async_trait;

use crate::{
    error::{ProguardError, ResolveError, UnhandledError},
    frames::{Frame, RawFrame},
    metric_consts::JAVA_EXCEPTION_REMAP_FAILED,
    symbol_store::{chunk_id::OrChunkId, proguard::ProguardRef},
    types::{operator::TeamId, Exception},
};
use tracing::warn;
pub mod local;

#[async_trait]
pub trait SymbolResolver: Send + Sync + 'static {
    async fn resolve_raw_frame(
        &self,
        team_id: TeamId,
        frame: &RawFrame,
    ) -> Result<Vec<Frame>, UnhandledError>;

    async fn resolve_java_class(
        &self,
        team_id: TeamId,
        symbolset_ref: OrChunkId<ProguardRef>,
        class: String,
    ) -> Result<String, ResolveError>;

    async fn resolve_dart_minified_name(
        &self,
        team_id: TeamId,
        symbolset_ref: String,
        minified_name: &str,
    ) -> Result<String, ResolveError>;

    async fn resolve_java_exception(
        &self,
        team_id: TeamId,
        mut exception: Exception,
    ) -> Result<Exception, UnhandledError> {
        let resolve_java_module_and_type =
            async |exception: &Exception| -> Result<(String, String), ResolveError> {
                if let RawFrame::Java(java_frame) = exception
                    .get_raw_frame()
                    .first()
                    .ok_or(ProguardError::NoOriginalFrames)
                    .map_err(ResolveError::from)?
                {
                    let module = exception
                        .module
                        .clone()
                        .ok_or(ProguardError::NoModuleProvided)
                        .map_err(ResolveError::from)?;

                    let exc_type = exception.exception_type.clone();

                    let class = format!("{}.{}", module, exc_type);
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
                exception.exception_type = new_type
            }
            Err(ResolveError::ResolutionError(frame_error)) => {
                warn!(
                    "Failed to resolve Java exception module and type: {}",
                    frame_error
                );
                // Handle resolution error
                metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => frame_error.to_string())
                    .increment(1)
            }
            Err(ResolveError::UnhandledError(err)) => {
                // Handle no original frames error
                return Err(err);
            }
        };

        Ok(exception)
    }

    async fn resolve_dart_exception(
        &self,
        team_id: TeamId,
        exception: Exception,
    ) -> Result<Exception, UnhandledError> {
        let frames = exception.get_raw_frame();
        let chunk_id = frames.iter().find_map(|frame| match frame {
            RawFrame::JavaScriptWeb(js_frame) => js_frame.chunk_id.clone(),
            RawFrame::JavaScriptNode(node_frame) => node_frame.chunk_id.clone(),
            RawFrame::LegacyJS(js_frame) => js_frame.chunk_id.clone(),
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
            Err(ResolveError::ResolutionError(_)) => Ok(exception), // If we can't resolve, return the original exception
            Err(ResolveError::UnhandledError(err)) => Err(err),
        }
    }
}

fn split_last_dot(s: &str) -> Result<(String, String), ResolveError> {
    let mut parts = s.rsplitn(2, '.');
    let last = parts.next().unwrap();
    let before = parts.next().ok_or(ProguardError::InvalidClass)?;
    Ok((before.to_string(), last.to_string()))
}
