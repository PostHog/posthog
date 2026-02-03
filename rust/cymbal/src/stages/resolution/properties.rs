use crate::{
    error::UnhandledError,
    stages::resolution::ResolutionStage,
    types::{event::ExceptionEvent, operator::Operator},
};

#[derive(Clone)]
pub struct PropertiesResolver;

impl Operator<ResolutionStage> for PropertiesResolver {
    type Input = ExceptionEvent;
    type Output = ExceptionEvent;

    async fn execute(
        &self,
        mut event: ExceptionEvent,
        _: &ResolutionStage,
    ) -> Result<ExceptionEvent, UnhandledError> {
        // Implement property resolution logic here
        event.exception_functions = Some(event.exception_list.get_unique_functions());
        event.exception_sources = Some(event.exception_list.get_unique_sources());
        event.exception_types = Some(event.exception_list.get_unique_types());
        event.exception_messages = Some(event.exception_list.get_unique_messages());
        Ok(event)
    }
}
