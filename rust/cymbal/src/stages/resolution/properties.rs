use crate::{
    error::UnhandledError,
    stages::resolution::ResolutionStage,
    types::{
        event::ExceptionEvent,
        operator::{OperatorResult, ValueOperator},
        pipeline::ExceptionEventHandledError,
    },
};

#[derive(Clone)]
pub struct PropertiesResolver;

impl ValueOperator for PropertiesResolver {
    type Item = ExceptionEvent;
    type Context = ResolutionStage;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    async fn execute_value(
        &self,
        mut event: ExceptionEvent,
        _: ResolutionStage,
    ) -> OperatorResult<Self> {
        // Implement property resolution logic here
        event.exception_functions = Some(event.exception_list.get_unique_functions());
        event.exception_sources = Some(event.exception_list.get_unique_sources());
        event.exception_types = Some(event.exception_list.get_unique_types());
        event.exception_messages = Some(event.exception_list.get_unique_messages());
        Ok(Ok(event))
    }
}
