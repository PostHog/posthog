use metrics::counter;

use crate::{
    error::{EventError, UnhandledError},
    issue_resolution::IssueStatus,
    metric_consts::{ISSUE_SUPPRESSION_OPERATOR, SUPPRESSED_ISSUE_DROPPED_EVENTS},
    stages::{linking::LinkingStage, pipeline::ExceptionEventHandledError},
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone)]
pub struct IssueSuppression;

impl ValueOperator for IssueSuppression {
    type Item = ExceptionProperties;
    type Context = LinkingStage;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        ISSUE_SUPPRESSION_OPERATOR
    }

    async fn execute_value(&self, input: Self::Item, _: LinkingStage) -> OperatorResult<Self> {
        if let Some(issue) = input.issue.as_ref() {
            if matches!(issue.status, IssueStatus::Suppressed) {
                counter!(SUPPRESSED_ISSUE_DROPPED_EVENTS).increment(1);
                return Ok(Err(ExceptionEventHandledError::new(
                    input.uuid,
                    EventError::Suppressed(issue.id),
                )));
            }
        }

        Ok(Ok(input))
    }
}
