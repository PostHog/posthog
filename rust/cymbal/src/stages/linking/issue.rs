use std::sync::Arc;

use chrono::{DateTime, Utc};
use common_types::format::parse_datetime_assuming_utc;
use sqlx::{Acquire, PgConnection};
use tracing::warn;

use crate::{
    app_context::AppContext,
    assignment_rules::{try_assignment_rules, Assignment},
    error::UnhandledError,
    issue_resolution::{
        send_issue_created_alert, send_issue_reopened_alert, send_new_fingerprint_event, Issue,
        IssueFingerprintOverride,
    },
    metric_consts::{ISSUE_CREATED, ISSUE_LINKER_OPERATOR},
    posthog_utils::capture_issue_created,
    stages::{linking::LinkingStage, pipeline::ExceptionEventHandledError},
    teams::TeamManager,
    types::{
        exception_properties::ExceptionProperties,
        operator::{OperatorResult, ValueOperator},
        OutputErrProps,
    },
};

#[derive(Clone)]
pub struct IssueLinker;

impl IssueLinker {
    pub async fn fetch_or_create_issue(
        input: ExceptionProperties,
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

        // Resolve issue (create new or find existing)
        let issue = resolve_issue(ctx.as_ref(), name, description, event_timestamp, input).await?;
        Ok(issue)
    }
}

impl ValueOperator for IssueLinker {
    type Item = ExceptionProperties;
    type Context = LinkingStage;
    type HandledError = ExceptionEventHandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        ISSUE_LINKER_OPERATOR
    }

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
        input.issue = Some(issue);

        Ok(Ok(input))
    }
}

async fn resolve_issue(
    context: &AppContext,
    name: String,
    description: String,
    event_timestamp: DateTime<Utc>,
    event_properties: ExceptionProperties,
) -> Result<Issue, UnhandledError> {
    let team_id = event_properties.team_id;
    let fingerprint = event_properties
        .fingerprint
        .clone()
        .ok_or(UnhandledError::Other("Missing fingerprint".into()))?;

    let mut conn = context.posthog_pool.acquire().await?;
    // Fast path - just fetch the issue directly, and then reopen it if needed
    let existing_issue = Issue::load_by_fingerprint(&mut *conn, team_id, &fingerprint).await?;
    if let Some(mut issue) = existing_issue {
        if issue.maybe_reopen(&mut *conn).await? {
            let assignment =
                process_assignment(&mut conn, &context.team_manager, &issue, &event_properties)
                    .await?;
            let output_props: OutputErrProps = event_properties.to_output(issue.id)?;
            send_issue_reopened_alert(context, &issue, assignment, output_props, &event_timestamp)
                .await?;
        }
        return Ok(issue);
    }

    // Slow path - insert a new issue, and then insert the fingerprint override, rolling
    // back the transaction if the override insert fails (since that indicates someone else
    // beat us to creating this new issue). Then, possibly reopen the issue.

    // Start a transaction, so we can roll it back on override insert failure
    let mut txn = conn.begin().await?;
    // Insert a new issue
    let issue = Issue::insert_new(
        team_id,
        name.to_string(),
        description.to_string(),
        &mut *txn,
    )
    .await?;

    // Insert the fingerprint override
    let issue_override = IssueFingerprintOverride::create_or_load(
        &mut *txn,
        team_id,
        &fingerprint,
        &issue,
        event_timestamp,
    )
    .await?;

    // If we actually inserted a new row for the issue override, commit the transaction,
    // saving both the issue and the override. Otherwise, rollback the transaction, and
    // use the retrieved issue override.
    let was_created = issue_override.issue_id == issue.id;
    let mut issue = issue;
    if !was_created {
        txn.rollback().await?;
        // Replace the attempt issue with the existing one
        issue = Issue::load(&mut *conn, team_id, issue_override.id)
            .await?
            .unwrap_or(issue);

        // Since we just loaded an issue, check if it needs to be reopened
        if issue.maybe_reopen(&mut *conn).await? {
            let assignment =
                process_assignment(&mut conn, &context.team_manager, &issue, &event_properties)
                    .await?;
            let output_props: OutputErrProps = event_properties.to_output(issue.id)?;
            send_issue_reopened_alert(context, &issue, assignment, output_props, &event_timestamp)
                .await?;
        }
    } else {
        metrics::counter!(ISSUE_CREATED).increment(1);
        let assignment =
            process_assignment(&mut txn, &context.team_manager, &issue, &event_properties).await?;

        let output_props = event_properties.clone().to_output(issue.id)?;
        send_new_fingerprint_event(context, &issue, &output_props).await?;
        send_issue_created_alert(context, &issue, assignment, output_props, &event_timestamp)
            .await?;
        txn.commit().await?;
        capture_issue_created(
            team_id,
            issue_override.issue_id,
            event_properties.props.contains_key("$sentry_event_id"),
        );
    };

    Ok(issue)
}

pub async fn process_assignment(
    conn: &mut PgConnection,
    team_manager: &TeamManager,
    issue: &Issue,
    exception_props: &ExceptionProperties,
) -> Result<Option<Assignment>, UnhandledError> {
    let output_props = exception_props.to_output(issue.id)?;
    let new_assignment =
        try_assignment_rules(conn, team_manager, issue.clone(), &output_props).await?;

    let assignment = if let Some(new_assignment) = new_assignment {
        Some(new_assignment.apply(&mut *conn, issue.id).await?)
    } else {
        issue.get_assignments(&mut *conn).await?.first().cloned()
    };

    Ok(assignment)
}
