use crate::{
    error::UnhandledError,
    frames::RawFrame,
    metric_consts::EXCEPTION_RESOLVER_OPERATOR,
    stages::{pipeline::ExceptionEventHandledError, resolution::ResolutionStage},
    types::{
        batch::Batch,
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
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
        // Checking if the exception is a Dart exception
        exc.exception_type.starts_with("minified:")
    }
}

impl ValueOperator for ExceptionResolver {
    type Context = ResolutionStage;
    type Item = ExceptionProperties;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        EXCEPTION_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut evt: ExceptionProperties,
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
