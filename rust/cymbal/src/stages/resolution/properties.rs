use crate::{
    error::UnhandledError,
    metric_consts::PROPERTIES_RESOLVER_OPERATOR,
    stages::{pipeline::ExceptionEventHandledError, resolution::ResolutionStage},
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone)]
pub struct PropertiesResolver;

impl ValueOperator for PropertiesResolver {
    type Item = ExceptionProperties;
    type Context = ResolutionStage;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        PROPERTIES_RESOLVER_OPERATOR
    }

    async fn execute_value(
        &self,
        mut event: ExceptionProperties,
        _: ResolutionStage,
    ) -> OperatorResult<Self> {
        // Implement property resolution logic here
        event.exception_functions = Some(event.exception_list.get_unique_functions());
        event.exception_sources = Some(event.exception_list.get_unique_sources());
        event.exception_types = Some(event.exception_list.get_unique_types());
        event.exception_messages = Some(event.exception_list.get_unique_messages());
        event.exception_releases = event.exception_list.get_release_map();
        Ok(Ok(event))
    }
}
