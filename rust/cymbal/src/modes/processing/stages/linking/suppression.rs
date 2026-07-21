use metrics::counter;

use crate::{
    error::{EventError, UnhandledError},
    issue_resolution::IssueStatus,
    metric_consts::{ISSUE_SUPPRESSION_OPERATOR, SUPPRESSED_ISSUE_DROPPED_EVENTS},
    stages::{linking::LinkingStage, pipeline::HandledError},
    types::{
        exception_event::{ExceptionEvent, Linked},
        operator::{OperatorResult, ValueOperator},
    },
};

#[derive(Clone)]
pub struct IssueSuppression;

impl ValueOperator for IssueSuppression {
    type Item = ExceptionEvent<Linked>;
    type Context = LinkingStage;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        ISSUE_SUPPRESSION_OPERATOR
    }

    async fn execute_value(&self, input: Self::Item, _: LinkingStage) -> OperatorResult<Self> {
        let issue = input.issue();
        if matches!(issue.status, IssueStatus::Suppressed) {
            counter!(SUPPRESSED_ISSUE_DROPPED_EVENTS).increment(1);
            return Ok(Err(EventError::Suppressed(issue.id)));
        }

        Ok(Ok(input))
    }
}
