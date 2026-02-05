use crate::{
    error::{EventError, UnhandledError},
    issue_resolution::IssueStatus,
    stages::linking::LinkingStage,
    types::{
        event::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
        pipeline::ExceptionEventHandledError,
    },
};

#[derive(Clone)]
pub struct IssueSuppression;

impl ValueOperator for IssueSuppression {
    type Item = ExceptionProperties;
    type Context = LinkingStage;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    async fn execute_value(&self, input: Self::Item, _: LinkingStage) -> OperatorResult<Self> {
        if let Some(issue) = input.issue.as_ref() {
            if matches!(issue.status, IssueStatus::Suppressed) {
                return Ok(Err(ExceptionEventHandledError::new(
                    input.uuid,
                    EventError::Suppressed(issue.id),
                )));
            }
        }

        Ok(Ok(input))
    }
}
