use std::sync::Arc;

use chrono::Utc;
use common_types::format::parse_datetime_assuming_utc;
use tracing::warn;

use crate::{
    app_context::AppContext,
    error::{EventError, UnhandledError},
    fingerprinting::Fingerprint,
    issue_resolution::{resolve_issue, Issue},
    stages::linking::LinkingStage,
    types::{
        event::ExceptionEvent,
        operator::{OperatorResult, ValueOperator},
        FingerprintedErrProps,
    },
};

#[derive(Clone)]
pub struct IssueLinker;

impl IssueLinker {
    pub async fn fetch_or_create_issue(
        input: ExceptionEvent,
        ctx: Arc<AppContext>,
    ) -> Result<Issue, UnhandledError> {
        // Extract name and description for the issue
        let name = input
            .proposed_issue_name
            .clone()
            .unwrap_or_else(|| input.exception_list[0].exception_type.clone());

        let description = input
            .proposed_issue_description
            .clone()
            .unwrap_or_else(|| input.exception_list[0].exception_message.clone());

        let event_timestamp = parse_datetime_assuming_utc(&input.timestamp).unwrap_or_else(|e| {
            warn!(
                event = input.uuid.to_string(),
                "Failed to get event timestamp, using current time, error: {:?}", e
            );
            Utc::now()
        });

        let team_id = input.team_id;
        let fingerprinted: FingerprintedErrProps = input.clone().into();

        // Resolve issue (create new or find existing)
        let issue = resolve_issue(
            ctx.as_ref(),
            team_id,
            name,
            description,
            event_timestamp,
            fingerprinted.clone(),
        )
        .await?;
        Ok(issue)
    }
}

impl ValueOperator for IssueLinker {
    type Item = ExceptionEvent;
    type Context = LinkingStage;
    type HandledError = EventError;
    type UnhandledError = UnhandledError;

    async fn execute_value(
        &self,
        mut input: Self::Item,
        ctx: LinkingStage,
    ) -> OperatorResult<Self> {
        let fingerprint = input.fingerprint.clone().unwrap();
        let cloned_input = input.clone();
        let issue: Issue = ctx
            .issue_cache
            .try_get_with((input.team_id, fingerprint), async move {
                Self::fetch_or_create_issue(cloned_input, ctx.app_context.clone()).await
            })
            .await
            .map_err(|e: Arc<UnhandledError>| UnhandledError::Other(e.to_string()))?;

        input.issue_id = Some(issue.id);
        Ok(Ok(input))
    }
}

impl From<ExceptionEvent> for FingerprintedErrProps {
    fn from(event: ExceptionEvent) -> Self {
        FingerprintedErrProps {
            proposed_issue_name: event.proposed_issue_name,
            proposed_issue_description: event.proposed_issue_description,
            exception_list: event.exception_list,
            fingerprint: Fingerprint {
                value: event.fingerprint.unwrap(),
                record: event.fingerprint_record.unwrap(),
                assignment: None,
            },
            proposed_fingerprint: event.proposed_fingerprint.unwrap(),
            handled: event.exception_handled,
            // WARN: props do not contain all values since they have been parsed before
            other: event.props,
        }
    }
}
