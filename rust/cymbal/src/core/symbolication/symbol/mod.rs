use async_trait::async_trait;

use crate::{
    core::ids::TeamId,
    core::types::Exception,
    error::{ProguardError, ResolveError, UnhandledError},
    frames::{Frame, RawFrame},
    langs::native::DebugImage,
    metric_consts::JAVA_EXCEPTION_REMAP_FAILED,
    symbolication::symbol_store::{chunk_id::OrChunkId, proguard::ProguardRef},
};
use tracing::debug;
use uuid::Uuid;
pub mod local;
pub mod records;

#[async_trait]
pub trait SymbolResolver: Send + Sync + 'static {
    async fn resolve_raw_frame(
        &self,
        team_id: TeamId,
        frame: &RawFrame,
        debug_images: &[DebugImage],
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

    /// The newest release bound to any of `symbol_set_refs`. Lives here because only a resolver
    /// backed by the symbol-set store can answer it; resolvers without one (test fakes) inherit
    /// the "no release" default.
    async fn latest_release_id(
        &self,
        _team_id: TeamId,
        _symbol_set_refs: &[String],
    ) -> Result<Option<Uuid>, UnhandledError> {
        Ok(None)
    }

    async fn resolve_java_exception(
        &self,
        team_id: TeamId,
        mut exception: Exception,
    ) -> Result<Exception, UnhandledError> {
        // Pick the first Java frame that carries a ProGuard mapping ref,
        // not just the first frame. Wire-order normalization can move a
        // ref-less framework frame to the front, so anchoring on the
        // frame that actually has a `map_id` keeps class remapping
        // order-independent.
        let symbolset_ref = exception
            .get_raw_frame()
            .iter()
            .find_map(|frame| match frame {
                RawFrame::Java(java_frame) => java_frame.get_ref().ok(),
                _ => None,
            });

        // When no frame in the stack carries a map_id, the whole exception came from an
        // unobfuscated JVM app, so `exception_type` and `module` already hold the real
        // class name and there is nothing to remap. Return early instead of attempting
        // the lookup, which would log and increment JAVA_EXCEPTION_REMAP_FAILED once per
        // event for traffic that was never obfuscated in the first place. A map_id that
        // is present but whose mapping is missing still falls through to the error arm
        // below, because that is a genuine failure.
        let Some(symbolset_ref) = symbolset_ref else {
            return Ok(exception);
        };

        let resolve_java_module_and_type =
            async |exception: &Exception,
                   symbolset_ref: OrChunkId<ProguardRef>|
                   -> Result<(String, String), ResolveError> {
                let module = exception
                    .module
                    .clone()
                    .ok_or(ProguardError::NoModuleProvided)
                    .map_err(ResolveError::from)?;

                let exc_type = exception.exception_type.clone();

                let class = format!("{}.{}", module, exc_type);

                let new_class = self
                    .resolve_java_class(team_id, symbolset_ref, class)
                    .await?;

                let (new_module, new_type) = split_last_dot(new_class.as_str())?;
                Ok((new_module, new_type))
            };

        match resolve_java_module_and_type(&exception, symbolset_ref).await {
            Ok((new_module, new_type)) => {
                exception.module = Some(new_module);
                exception.exception_type = new_type
            }
            Err(ResolveError::ResolutionError(frame_error)) => {
                debug!(
                    team_id,
                    reason = frame_error.metric_reason(),
                    error = %frame_error,
                    "failed to resolve Java exception module and type"
                );
                metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => frame_error.metric_reason())
                    .increment(1)
            }
            Err(ResolveError::UnhandledError(err)) => {
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

#[cfg(test)]
mod tests {
    use crate::{
        core::types::Stacktrace,
        langs::{java::RawJavaFrame, CommonFrameMetadata},
    };

    use super::*;

    // A resolver whose class-remapping path panics, so the test below fails loudly if
    // `resolve_java_exception` attempts a lookup it was supposed to skip.
    struct NeverResolves;

    #[async_trait]
    impl SymbolResolver for NeverResolves {
        async fn resolve_raw_frame(
            &self,
            _team_id: TeamId,
            _frame: &RawFrame,
            _debug_images: &[DebugImage],
        ) -> Result<Vec<Frame>, UnhandledError> {
            unreachable!("frame resolution is not exercised here")
        }

        async fn resolve_java_class(
            &self,
            _team_id: TeamId,
            _symbolset_ref: OrChunkId<ProguardRef>,
            _class: String,
        ) -> Result<String, ResolveError> {
            panic!("must not look up a mapping when no frame carries a map_id")
        }

        async fn resolve_dart_minified_name(
            &self,
            _team_id: TeamId,
            _symbolset_ref: String,
            _minified_name: &str,
        ) -> Result<String, ResolveError> {
            unreachable!("dart resolution is not exercised here")
        }
    }

    fn java_exception(map_id: Option<&str>) -> Exception {
        Exception {
            exception_id: None,
            exception_type: "IllegalStateException".to_string(),
            exception_message: "boom".to_string(),
            mechanism: None,
            module: Some("java.lang".to_string()),
            thread_id: None,
            stack: Some(Stacktrace::Raw {
                frames: vec![RawFrame::Java(RawJavaFrame {
                    filename: Some("InvoiceService.java".to_string()),
                    function: "charge".to_string(),
                    lineno: Some(42),
                    module: "com.acme.billing.InvoiceService".to_string(),
                    map_id: map_id.map(ToString::to_string),
                    context_line: None,
                    pre_context: Vec::new(),
                    post_context: Vec::new(),
                    method_synthetic: false,
                    meta: CommonFrameMetadata::default(),
                })],
            }),
        }
    }

    #[tokio::test]
    async fn unobfuscated_java_exceptions_skip_the_remap_attempt() {
        let result = NeverResolves
            .resolve_java_exception(1, java_exception(None))
            .await
            .unwrap();

        // The type and module come back untouched, and no lookup was attempted: the stub
        // resolver panics if one is, which is what keeps JAVA_EXCEPTION_REMAP_FAILED from
        // firing once per event on unobfuscated JVM traffic.
        assert_eq!(result.exception_type, "IllegalStateException");
        assert_eq!(result.module.as_deref(), Some("java.lang"));
    }
}
