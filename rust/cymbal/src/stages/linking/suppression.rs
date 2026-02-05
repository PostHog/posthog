use crate::{
    error::EventError,
    issue_resolution::IssueStatus,
    stages::linking::LinkingStage,
    types::{
        event::ExceptionEvent,
        operator::{Operator, ValueOperator},
    },
};

#[derive(Clone)]
pub struct IssueSuppression;

impl ValueOperator for IssueSuppression {
    type Item = ExceptionEvent;
    type Context = LinkingStage;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    async fn execute_value(
        &self,
        mut input: Self::Item,
        ctx: LinkingStage,
    ) -> OperatorResult<Self> {
        if let Some(issue) = input.issue {
            if matches!(issue.status, IssueStatus::Suppressed) {
                return Err(EventError::Suppressed(issue.id));
            }
        } else {
            Ok(input)
        }
    }
}
