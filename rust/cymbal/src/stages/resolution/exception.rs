use crate::{
    error::UnhandledError,
    frames::RawFrame,
    stages::resolution::ResolutionStage,
    types::{
        batch::Batch,
        event::ExceptionEvent,
        operator::{OperatorResult, ValueOperator},
        pipeline::ExceptionEventHandledError,
        Exception, ExceptionList,
    },
};

#[derive(Clone)]
pub struct ExceptionResolver;

impl ExceptionResolver {
    pub fn is_java_exception(exc: &Exception) -> bool {
        let first_frame = exc.stack.as_ref().and_then(|s| s.get_raw_frames().first());
        // Implementation for checking if the exception is a Java exception
        if let Some(RawFrame::Java(_)) = first_frame {
            if exc.module.is_some() {
                return true;
            }
        }
        false
    }

    pub fn is_dart_exception(exc: &Exception) -> bool {
        // Implementation for checking if the exception is a Dart exception
        exc.exception_type.starts_with("minified:")
    }
}

impl ValueOperator for ExceptionResolver {
    type Context = ResolutionStage;
    type Item = ExceptionEvent;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    async fn execute_value(
        &self,
        mut evt: ExceptionEvent,
        ctx: ResolutionStage,
    ) -> OperatorResult<Self> {
        evt.exception_list = Batch::from(evt.exception_list.0)
            .apply_func(
                move |exc, ctx| async move {
                    let ctx = ctx.clone();
                    if ExceptionResolver::is_java_exception(&exc) {
                        ctx.symbol_resolver
                            .resolve_java_exception(evt.team_id, exc)
                            .await
                    } else if ExceptionResolver::is_dart_exception(&exc) {
                        ctx.symbol_resolver
                            .resolve_dart_exception(evt.team_id, exc)
                            .await
                    } else {
                        Ok(exc)
                    }
                },
                ctx,
            )
            .await
            .map(|v| ExceptionList::from(Vec::from(v)))?;

        Ok(Ok(evt))
    }
}
