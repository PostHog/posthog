use std::sync::Arc;

use chrono::{DateTime, Utc};
use common_types::format::parse_datetime_assuming_utc;
use sqlx::{Acquire, PgConnection};
use tracing::warn;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    issue_resolution::{
        send_fingerprint_issue_state, send_issue_created_notification,
        send_issue_reopened_notification, Issue, IssueFingerprintOverride,
    },
    metric_consts::{FINGERPRINT_VERSION_USED, ISSUE_CREATED, ISSUE_LINKER_OPERATOR},
    modes::processing::rules::assignment::{try_assignment_rules, Assignment},
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

// The issue an event resolved to, together with the fingerprint that actually matched or
// created it — the event's `$exception_fingerprint` is rewritten to this value.
#[derive(Debug, Clone)]
pub struct ResolvedIssue {
    pub issue: Issue,
    pub fingerprint: String,
}

// The fingerprints to resolve against, in lookup order, labeled for metrics. Events with a
// manual fingerprint or a matched grouping rule have no versioned fingerprints and resolve
// against their single explicit fingerprint, exactly as before versioning existed.
fn candidate_fingerprints(input: &ExceptionProperties) -> Vec<(&'static str, String)> {
    if input.versioned_fingerprints.is_empty() {
        return vec![(
            "custom",
            input
                .fingerprint
                .clone()
                .expect("fingerprint is set by the grouping stage"),
        )];
    }
    input
        .versioned_fingerprints
        .iter()
        .map(|v| (v.version.as_str(), v.fingerprint.value.clone()))
        .collect()
}

impl IssueLinker {
    pub async fn fetch_or_create_issue(
        input: &ExceptionProperties,
        ctx: Arc<AppContext>,
    ) -> Result<ResolvedIssue, UnhandledError> {
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
        let resolved =
            resolve_issue(ctx.as_ref(), name, description, event_timestamp, input).await?;
        Ok(resolved)
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

    async fn execute_value(&self, input: Self::Item, ctx: LinkingStage) -> OperatorResult<Self> {
        // Cache keys are the composite of all candidate fingerprints: the full input to the
        // resolution decision, so two events resolve identically iff their keys are equal.
        let candidates = candidate_fingerprints(&input);
        let key = (input.team_id, composite_key(&candidates));

        // Wrap the (large) event in an `Arc` so the cache-loader closures capture a cheap
        // refcount bump instead of a full deep clone. The loaders only ever borrow the
        // event, and they don't run at all on the warm-cache path, so on the hot path this
        // is one `Arc` allocation and no `ExceptionProperties` copies.
        let input = Arc::new(input);

        // Two-layer cache: per-batch dedup wraps the cross-request `issue_id` cache.
        // - Per-batch cache (this `try_get_with`): events with the same fingerprints in
        //   the same batch resolve the Issue exactly once. moka serializes concurrent
        //   misses for the same key inside the batch.
        // - Cross-batch `issue_id` cache (inside `resolve_via_id_cache`): keeps the
        //   `(team_id, fingerprints) -> issue_id` mapping warm across batches and
        //   skips the expensive fingerprint JOIN on warm fingerprints.
        // Status is always read fresh from PG inside the loader, so `IssueSuppression`
        // and `maybe_reopen` never see stale state.
        let input_for_load = input.clone();
        let ctx_for_load = ctx.clone();
        let resolved: ResolvedIssue = ctx
            .batch_issue_cache
            .try_get_with(key, async move {
                resolve_via_id_cache(input_for_load, &ctx_for_load).await
            })
            .await
            .map_err(|e: Arc<UnhandledError>| UnhandledError::Other(e.to_string()))?;

        // The only `Arc` clones were captured by this call's loader closures, which have
        // all completed (or been dropped when moka deduped them), so we uniquely own the
        // event again and can reclaim it to write back the resolved issue.
        let mut input =
            Arc::into_inner(input).expect("input Arc uniquely held after cache resolution");

        // The event carries the fingerprint that actually resolved the issue: on versioned
        // events that may be a newer algorithm version than the primary set at grouping.
        if let Some(used) = input
            .versioned_fingerprints
            .iter()
            .find(|v| v.fingerprint.value == resolved.fingerprint)
        {
            input.fingerprint = Some(used.fingerprint.value.clone());
            input.fingerprint_record = Some(used.fingerprint.record.clone());
        }
        input.issue_id = Some(resolved.issue.id);
        input.issue = Some(resolved.issue);

        Ok(Ok(input))
    }
}

fn composite_key(candidates: &[(&'static str, String)]) -> String {
    candidates
        .iter()
        .map(|(_, value)| value.as_str())
        .collect::<Vec<_>>()
        .join("\n")
}

// Resolves an issue by going through the cross-batch `issue_id` cache:
// - On cache miss we run `fetch_or_create_issue` (the only place that fires
//   `created` / `reopened` alerts) and return the freshly-loaded Issue directly,
//   avoiding a redundant PK lookup.
// - On cache hit we re-read by id (cheap PK lookup) and call `maybe_reopen` so
//   suppression and reopen always see current PG state.
async fn resolve_via_id_cache(
    input: Arc<ExceptionProperties>,
    ctx: &LinkingStage,
) -> Result<ResolvedIssue, UnhandledError> {
    let candidates = candidate_fingerprints(&input);
    let key = (input.team_id, composite_key(&candidates));

    // `try_get_with` only returns the cached value, so we stash the freshly resolved
    // `ResolvedIssue` in a slot when we run the loader ourselves. That lets us reuse it
    // below and skip a redundant `Issue::load` on the cache-miss path.
    let just_resolved: Arc<std::sync::Mutex<Option<ResolvedIssue>>> = Default::default();
    let slot = just_resolved.clone();
    let app_ctx = ctx.app_context.clone();
    let cloned_input = input.clone();

    let (issue_id, used_fingerprint): (Uuid, String) = ctx
        .issue_cache
        .try_get_with(key.clone(), async move {
            let resolved =
                IssueLinker::fetch_or_create_issue(cloned_input.as_ref(), app_ctx).await?;
            let cached = (resolved.issue.id, resolved.fingerprint.clone());
            *slot.lock().expect("just_resolved mutex poisoned") = Some(resolved);
            Ok::<(Uuid, String), UnhandledError>(cached)
        })
        .await
        .map_err(|e: Arc<UnhandledError>| UnhandledError::Other(e.to_string()))?;

    // If we ran the loader, the just-resolved Issue is current — return it directly.
    if let Some(resolved) = just_resolved
        .lock()
        .expect("just_resolved mutex poisoned")
        .take()
    {
        return Ok(resolved);
    }

    // Cache hit (or we were deduped against a concurrent caller). Refresh by id.
    match load_and_maybe_reopen(
        ctx.app_context.as_ref(),
        input.team_id,
        issue_id,
        &used_fingerprint,
        &input,
    )
    .await?
    {
        Some(issue) => Ok(ResolvedIssue {
            issue,
            fingerprint: used_fingerprint,
        }),
        None => {
            // Cached id no longer exists in PG. Invalidate and run the slow path.
            ctx.issue_cache.invalidate(&key).await;
            IssueLinker::fetch_or_create_issue(input.as_ref(), ctx.app_context.clone()).await
        }
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
    send_issue_reopened_notification(context, &issue, assignment, output_props, &event_timestamp)
        .await?;

    Ok(Some(issue))
}

async fn resolve_issue(
    context: &AppContext,
    name: String,
    description: String,
    event_timestamp: DateTime<Utc>,
    event_properties: &ExceptionProperties,
) -> Result<ResolvedIssue, UnhandledError> {
    let team_id = event_properties.team_id;
    if event_properties.fingerprint.is_none() {
        return Err(UnhandledError::Other("Missing fingerprint".into()));
    }
    let candidates = candidate_fingerprints(event_properties);

    let mut conn = context.posthog_pool.acquire().await?;
    // Fast path - the first candidate fingerprint (oldest algorithm version first) that
    // already maps to an issue wins; reopen it if needed.
    for (version, candidate) in &candidates {
        let Some(result) = Issue::load_by_fingerprint(&mut *conn, team_id, candidate).await? else {
            continue;
        };
        let (mut issue, fingerprint_first_seen) = result.into_issue();
        if issue.maybe_reopen(&mut *conn).await? {
            let first_seen_for_state = fingerprint_first_seen.unwrap_or(issue.created_at);
            let assignment =
                process_assignment(&mut conn, &context.team_manager, &issue, event_properties)
                    .await?;
            send_fingerprint_issue_state(
                context,
                &issue,
                candidate,
                assignment.as_ref(),
                first_seen_for_state,
            )
            .await?;
            let output_props: OutputErrProps = event_properties.to_output(issue.id)?;
            drop(conn);
            send_issue_reopened_notification(
                context,
                &issue,
                assignment,
                output_props,
                &event_timestamp,
            )
            .await?;
        }
        metrics::counter!(FINGERPRINT_VERSION_USED, "version" => *version, "outcome" => "linked")
            .increment(1);
        return Ok(ResolvedIssue {
            issue,
            fingerprint: candidate.clone(),
        });
    }

    // No candidate matched: create the issue under the newest algorithm version's
    // fingerprint. Older versions stay unassociated — future events whose older fingerprint
    // matches an existing issue keep linking there (existing issues never re-fingerprint).
    let (version, fingerprint) = candidates
        .last()
        .expect("candidate_fingerprints is never empty")
        .clone();

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
                process_assignment(&mut conn, &context.team_manager, &issue, event_properties)
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
            send_issue_reopened_notification(
                context,
                &issue,
                assignment,
                output_props,
                &event_timestamp,
            )
            .await?;
        }
    } else {
        metrics::counter!(ISSUE_CREATED).increment(1);
        metrics::counter!(FINGERPRINT_VERSION_USED, "version" => version, "outcome" => "created")
            .increment(1);
        let assignment =
            process_assignment(&mut txn, &context.team_manager, &issue, event_properties).await?;

        let output_props = event_properties.to_output(issue.id)?;
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

        send_issue_created_notification(
            context,
            &issue,
            assignment,
            output_props,
            event_properties.uuid,
            &event_timestamp,
        )
        .await?;
    };

    Ok(ResolvedIssue { issue, fingerprint })
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
