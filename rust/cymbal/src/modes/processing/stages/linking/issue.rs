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
    metric_consts::{ISSUE_CREATED, ISSUE_LINKER_OPERATOR},
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

impl IssueLinker {
    pub async fn fetch_or_create_issue(
        input: &ExceptionProperties,
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

    async fn execute_value(&self, input: Self::Item, ctx: LinkingStage) -> OperatorResult<Self> {
        let fingerprint = input
            .fingerprint
            .clone()
            .ok_or_else(|| UnhandledError::Other("Missing fingerprint".into()))?;
        let key = (input.team_id, fingerprint);

        // Wrap the (large) event in an `Arc` so the cache-loader closures capture a cheap
        // refcount bump instead of a full deep clone. The loaders only ever borrow the
        // event, and they don't run at all on the warm-cache path, so on the hot path this
        // is one `Arc` allocation and no `ExceptionProperties` copies.
        let input = Arc::new(input);

        // Two-layer cache: per-batch dedup wraps the cross-request `issue_id` cache.
        // - Per-batch cache (this `try_get_with`): events with the same fingerprint in
        //   the same batch resolve the Issue exactly once. moka serializes concurrent
        //   misses for the same key inside the batch.
        // - Cross-batch `issue_id` cache (inside `resolve_via_id_cache`): keeps the
        //   `(team_id, fingerprint) -> issue_id` mapping warm across batches and
        //   skips the expensive fingerprint JOIN on warm fingerprints.
        // Status is always read fresh from PG inside the loader, so `IssueSuppression`
        // and `maybe_reopen` never see stale state.
        let input_for_load = input.clone();
        let ctx_for_load = ctx.clone();
        let issue: Issue = ctx
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
        input.issue_id = Some(issue.id);
        input.issue = Some(issue);

        Ok(Ok(input))
    }
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
) -> Result<Issue, UnhandledError> {
    let fingerprint = input
        .fingerprint
        .clone()
        .ok_or_else(|| UnhandledError::Other("Missing fingerprint".into()))?;
    let key = (input.team_id, fingerprint.clone());

    // `try_get_with` only returns the cached value (`Uuid`), so we stash the freshly
    // resolved Issue in a slot when we run the loader ourselves. That lets us reuse it
    // below and skip a redundant `Issue::load` on the cache-miss path.
    let just_resolved: Arc<std::sync::Mutex<Option<Issue>>> = Default::default();
    let slot = just_resolved.clone();
    let app_ctx = ctx.app_context.clone();
    let cloned_input = input.clone();

    let issue_id: Uuid = ctx
        .issue_cache
        .try_get_with(key.clone(), async move {
            let issue = IssueLinker::fetch_or_create_issue(&cloned_input, app_ctx).await?;
            let id = issue.id;
            *slot.lock().expect("just_resolved mutex poisoned") = Some(issue);
            Ok::<Uuid, UnhandledError>(id)
        })
        .await
        .map_err(|e: Arc<UnhandledError>| UnhandledError::Other(e.to_string()))?;

    // If we ran the loader, the just-resolved Issue is current — return it directly.
    if let Some(issue) = just_resolved
        .lock()
        .expect("just_resolved mutex poisoned")
        .take()
    {
        return Ok(issue);
    }

    // Cache hit (or we were deduped against a concurrent caller). Refresh by id.
    match load_and_maybe_reopen(
        ctx.app_context.as_ref(),
        input.team_id,
        issue_id,
        &fingerprint,
        &input,
    )
    .await?
    {
        Some(issue) => Ok(issue),
        None => {
            // Cached id no longer exists in PG. Invalidate and run the slow path.
            ctx.issue_cache.invalidate(&key).await;
            IssueLinker::fetch_or_create_issue(&input, ctx.app_context.clone()).await
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
        return Ok(issue);
    }

    // Continuity path - wire-order normalization changed this event's stored
    // order, so its canonical fingerprint differs from the one earlier
    // (pre-normalization) payloads produced. Before forking a fresh issue,
    // check whether the legacy-order fingerprint already maps to an issue; if
    // so, alias the canonical fingerprint onto that same issue so the group
    // stays intact across the flip.
    if let Some(issue) = maybe_alias_legacy_fingerprint(
        context,
        &mut conn,
        team_id,
        &fingerprint,
        event_properties,
        event_timestamp,
    )
    .await?
    {
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

    Ok(issue)
}

// When wire-order normalization changed this event's stored order, its
// canonical fingerprint had no issue yet. If the legacy-order fingerprint does
// map to an issue, alias the canonical fingerprint onto that same issue (a new
// fingerprint-override row pointing at the existing issue) so pre- and
// post-flip events keep grouping together. Returns the existing issue on a
// successful alias, or `None` to let the caller fall through to creating a new
// issue.
async fn maybe_alias_legacy_fingerprint(
    context: &AppContext,
    conn: &mut PgConnection,
    team_id: i32,
    canonical_fingerprint: &str,
    event_properties: &ExceptionProperties,
    event_timestamp: DateTime<Utc>,
) -> Result<Option<Issue>, UnhandledError> {
    let Some(legacy_fingerprint) = event_properties.legacy_fingerprint.as_deref() else {
        return Ok(None);
    };
    // Reversal was a no-op for fingerprinting (e.g. a single-frame stack), so
    // there's nothing to alias.
    if legacy_fingerprint == canonical_fingerprint {
        return Ok(None);
    }

    let Some(result) = Issue::load_by_fingerprint(&mut *conn, team_id, legacy_fingerprint).await?
    else {
        return Ok(None);
    };
    let (mut issue, legacy_first_seen) = result.into_issue();
    let first_seen = legacy_first_seen.unwrap_or(issue.created_at);

    // Insert the canonical override and send its fingerprint state atomically:
    // hold the override insert in a transaction that only commits after the
    // Kafka state message is produced. Otherwise a produce failure would leave
    // the override in PG while ClickHouse never learns the canonical
    // fingerprint -> issue mapping, and retries would take the fast
    // `load_by_fingerprint` path and never re-emit it. Mirrors the new-issue
    // slow path.
    let mut txn = conn.begin().await?;

    // Point the canonical fingerprint at the legacy issue. `create_or_load` is
    // idempotent under the (team_id, fingerprint) unique constraint, so a race
    // that inserted the canonical override first just returns that row.
    let alias = IssueFingerprintOverride::create_or_load(
        &mut *txn,
        team_id,
        canonical_fingerprint,
        &issue,
        first_seen,
    )
    .await?;

    // A concurrent writer already linked the canonical fingerprint to a
    // different issue — respect that mapping and hand back its issue instead.
    if alias.issue_id != issue.id {
        let Some(existing) = Issue::load(&mut *txn, team_id, alias.issue_id).await? else {
            return Ok(None);
        };
        issue = existing;
    }

    let reopened = issue.maybe_reopen(&mut *txn).await?;
    // Match the existing-issue convention: only evaluate assignment rules when
    // the issue was reopened. Aliasing onto an already-active issue must not
    // trigger auto-assignment the legacy-fingerprint path wouldn't have. In the
    // steady state we just carry the issue's current assignment into the state
    // message.
    let assignment = if reopened {
        process_assignment(&mut txn, &context.team_manager, &issue, event_properties).await?
    } else {
        issue.get_assignments(&mut *txn).await?.first().cloned()
    };
    send_fingerprint_issue_state(
        context,
        &issue,
        canonical_fingerprint,
        assignment.as_ref(),
        first_seen,
    )
    .await?;
    txn.commit().await?;

    if reopened {
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

    Ok(Some(issue))
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

#[cfg(test)]
mod test {
    use std::collections::HashMap;

    use sqlx::PgPool;

    use super::*;
    use crate::{test_utils::create_test_context, types::ExceptionList};

    fn props_with_legacy_fingerprint(
        team_id: i32,
        legacy_fingerprint: &str,
    ) -> ExceptionProperties {
        ExceptionProperties {
            exception_list: ExceptionList(vec![]),
            exception_sources: None,
            exception_types: None,
            exception_messages: None,
            exception_functions: None,
            exception_handled: None,
            exception_releases: HashMap::new(),
            fingerprint: None,
            proposed_fingerprint: None,
            fingerprint_record: None,
            issue_id: None,
            proposed_issue_name: None,
            proposed_issue_description: None,
            debug_images: vec![],
            props: HashMap::new(),
            uuid: Uuid::now_v7(),
            timestamp: String::new(),
            team_id,
            issue: None,
            legacy_order_exception_list: None,
            legacy_order_resolved: None,
            legacy_fingerprint: Some(legacy_fingerprint.to_string()),
        }
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn aliases_canonical_fingerprint_onto_legacy_issue(db: PgPool) {
        let ctx = create_test_context(db.clone()).await;
        let mut conn = db.acquire().await.unwrap();
        let team_id = 1;

        let legacy_issue = Issue::insert_new(team_id, "name".into(), "desc".into(), &mut *conn)
            .await
            .unwrap();
        IssueFingerprintOverride::create_or_load(
            &mut *conn,
            team_id,
            "legacy-fp",
            &legacy_issue,
            Utc::now(),
        )
        .await
        .unwrap();

        let props = props_with_legacy_fingerprint(team_id, "legacy-fp");
        let aliased = maybe_alias_legacy_fingerprint(
            &ctx,
            &mut conn,
            team_id,
            "canonical-fp",
            &props,
            Utc::now(),
        )
        .await
        .unwrap()
        .expect("should alias onto the legacy issue");
        assert_eq!(aliased.id, legacy_issue.id);

        // The canonical fingerprint now maps to the pre-flip issue, so
        // subsequent canonical events take the fast path to the same group.
        let (loaded, _) = Issue::load_by_fingerprint(&mut *conn, team_id, "canonical-fp")
            .await
            .unwrap()
            .expect("canonical override row should exist")
            .into_issue();
        assert_eq!(loaded.id, legacy_issue.id);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn falls_through_when_legacy_fingerprint_is_unknown(db: PgPool) {
        let ctx = create_test_context(db.clone()).await;
        let mut conn = db.acquire().await.unwrap();
        let team_id = 1;

        let props = props_with_legacy_fingerprint(team_id, "never-seen-fp");
        let aliased = maybe_alias_legacy_fingerprint(
            &ctx,
            &mut conn,
            team_id,
            "canonical-fp",
            &props,
            Utc::now(),
        )
        .await
        .unwrap();
        assert!(aliased.is_none(), "nothing to alias onto -> fall through");

        // Fall-through must not leave an override behind; issue creation is
        // the caller's job.
        assert!(
            Issue::load_by_fingerprint(&mut *conn, team_id, "canonical-fp")
                .await
                .unwrap()
                .is_none()
        );
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn respects_existing_canonical_mapping_over_legacy_issue(db: PgPool) {
        let ctx = create_test_context(db.clone()).await;
        let mut conn = db.acquire().await.unwrap();
        let team_id = 1;

        let legacy_issue = Issue::insert_new(team_id, "legacy".into(), "desc".into(), &mut *conn)
            .await
            .unwrap();
        IssueFingerprintOverride::create_or_load(
            &mut *conn,
            team_id,
            "legacy-fp",
            &legacy_issue,
            Utc::now(),
        )
        .await
        .unwrap();

        // A concurrent writer already linked the canonical fingerprint to a
        // different issue; the alias must hand back that mapping, not the
        // legacy issue.
        let winner = Issue::insert_new(team_id, "winner".into(), "desc".into(), &mut *conn)
            .await
            .unwrap();
        IssueFingerprintOverride::create_or_load(
            &mut *conn,
            team_id,
            "canonical-fp",
            &winner,
            Utc::now(),
        )
        .await
        .unwrap();

        let props = props_with_legacy_fingerprint(team_id, "legacy-fp");
        let aliased = maybe_alias_legacy_fingerprint(
            &ctx,
            &mut conn,
            team_id,
            "canonical-fp",
            &props,
            Utc::now(),
        )
        .await
        .unwrap()
        .expect("existing mapping should be returned");
        assert_eq!(aliased.id, winner.id);
    }
}
