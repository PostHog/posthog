use std::sync::Arc;

use chrono::{DateTime, Utc};
use common_types::format::parse_datetime_assuming_utc;
use sqlx::{Acquire, PgConnection};
use tracing::warn;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    assignment_rules::{try_assignment_rules, Assignment},
    error::UnhandledError,
    issue_resolution::{
        send_fingerprint_issue_state, send_issue_created_alert, send_issue_reopened_alert,
        send_new_fingerprint_event, Issue, IssueFingerprintOverride,
    },
    metric_consts::{ISSUE_CREATED, ISSUE_LINKER_OPERATOR},
    posthog_utils::capture_issue_created,
    stages::{linking::LinkingStage, pipeline::HandledError},
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
    type HandledError = HandledError;
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
        let key = (input.team_id, fingerprint.clone());

        // The cache holds only the stable `(team_id, fingerprint) -> issue_id` mapping
        // across requests. We deliberately do NOT cache the Issue itself: status changes
        // (suppression, resolution) made in PG would otherwise be ignored by
        // `IssueSuppression` and `maybe_reopen` until the cache TTL expired.
        let cloned_input = input.clone();
        let ctx_for_load = ctx.clone();
        let issue_id: Uuid = ctx
            .issue_cache
            .try_get_with(key.clone(), async move {
                let issue =
                    Self::fetch_or_create_issue(cloned_input, ctx_for_load.app_context.clone())
                        .await?;
                Ok::<Uuid, UnhandledError>(issue.id)
            })
            .await
            .map_err(|e: Arc<UnhandledError>| UnhandledError::Other(e.to_string()))?;

        // Always re-read current state. On the cache-miss path this is one redundant PK
        // lookup; on the cache-hit path it's the whole point — we replace the expensive
        // fingerprint JOIN with a cheap PK lookup while keeping status fresh.
        let issue = match load_and_maybe_reopen(
            ctx.app_context.as_ref(),
            input.team_id,
            issue_id,
            &fingerprint,
            &input,
        )
        .await?
        {
            Some(issue) => issue,
            None => {
                // The cached id no longer exists in PG (deleted issue). Invalidate and
                // run the full slow path, which will create a new issue if needed.
                ctx.issue_cache.invalidate(&key).await;
                Self::fetch_or_create_issue(input.clone(), ctx.app_context.clone()).await?
            }
        };

        input.issue_id = Some(issue.id);
        input.issue = Some(issue);

        Ok(Ok(input))
    }
}

// Loads the issue by id (fast PK lookup) and runs the reopen side effects if the issue
// is currently in a non-active, non-suppressed state. Returns `None` if the cached id
// is dangling (issue was deleted), so the caller can invalidate and fall back to a full
// resolve.
async fn load_and_maybe_reopen(
    context: &AppContext,
    team_id: i32,
    issue_id: Uuid,
    fingerprint: &str,
    event_properties: &ExceptionProperties,
) -> Result<Option<Issue>, UnhandledError> {
    let mut conn = context.posthog_pool.acquire().await?;
    let Some(mut issue) = Issue::load(&mut *conn, team_id, issue_id).await? else {
        return Ok(None);
    };

    if !issue.maybe_reopen(&mut *conn).await? {
        return Ok(Some(issue));
    }

    // Reopened — mirror the side effects from `resolve_issue`'s fast-path reopen branch.
    let event_timestamp =
        parse_datetime_assuming_utc(&event_properties.timestamp).unwrap_or_else(|e| {
            warn!(
                event = event_properties.uuid.to_string(),
                "Failed to get event timestamp, using current time, error: {:?}", e
            );
            Utc::now()
        });
    let assignment =
        process_assignment(&mut conn, &context.team_manager, &issue, event_properties).await?;
    // We don't carry a per-fingerprint `first_seen` through this path (we loaded by id,
    // not by fingerprint), so fall back to the issue's creation time the same way
    // `resolve_issue` already does when the join returns no first_seen.
    send_fingerprint_issue_state(
        context,
        &issue,
        fingerprint,
        assignment.as_ref(),
        issue.created_at,
    )
    .await?;
    let output_props: OutputErrProps = event_properties.to_output(issue.id)?;
    drop(conn);
    context
        .signal_client
        .emit_issue_reopened(&issue, &output_props);
    send_issue_reopened_alert(context, &issue, assignment, output_props, &event_timestamp).await?;

    Ok(Some(issue))
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
    if let Some(result) = existing_issue {
        let (mut issue, fingerprint_first_seen) = result.into_issue();
        if issue.maybe_reopen(&mut *conn).await? {
            let first_seen_for_state = fingerprint_first_seen.unwrap_or(issue.created_at);
            let assignment =
                process_assignment(&mut conn, &context.team_manager, &issue, &event_properties)
                    .await?;
            send_fingerprint_issue_state(
                context,
                &issue,
                &fingerprint,
                assignment.as_ref(),
                first_seen_for_state,
            )
            .await?;
            let output_props: OutputErrProps = event_properties.to_output(issue.id)?;
            drop(conn);
            context
                .signal_client
                .emit_issue_reopened(&issue, &output_props);
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
        let mut fingerprint_first_seen = None;
        if let Some(result) = Issue::load_by_fingerprint(&mut *conn, team_id, &fingerprint).await? {
            let (existing, first_seen) = result.into_issue();
            issue = existing;
            fingerprint_first_seen = first_seen;
        }

        // Since we just loaded an issue, check if it needs to be reopened
        if issue.maybe_reopen(&mut *conn).await? {
            let first_seen_for_state = fingerprint_first_seen.unwrap_or(issue.created_at);
            let assignment =
                process_assignment(&mut conn, &context.team_manager, &issue, &event_properties)
                    .await?;
            send_fingerprint_issue_state(
                context,
                &issue,
                &fingerprint,
                assignment.as_ref(),
                first_seen_for_state,
            )
            .await?;

            drop(conn);

            let output_props: OutputErrProps = event_properties.to_output(issue.id)?;
            context
                .signal_client
                .emit_issue_reopened(&issue, &output_props);
            send_issue_reopened_alert(context, &issue, assignment, output_props, &event_timestamp)
                .await?;
        }
    } else {
        metrics::counter!(ISSUE_CREATED).increment(1);
        let assignment =
            process_assignment(&mut txn, &context.team_manager, &issue, &event_properties).await?;

        let output_props = event_properties.clone().to_output(issue.id)?;
        send_new_fingerprint_event(context, &issue, &output_props).await?;
        send_fingerprint_issue_state(
            context,
            &issue,
            &fingerprint,
            assignment.as_ref(),
            event_timestamp,
        )
        .await?;

        txn.commit().await?;
        drop(conn);

        context
            .signal_client
            .emit_issue_created(&issue, &output_props);

        send_issue_created_alert(context, &issue, assignment, output_props, &event_timestamp)
            .await?;

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
