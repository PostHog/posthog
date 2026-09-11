# Subscription operations

## Schedule

Required create fields include `frequency`, `interval`, and `start_date`.

- Set `frequency` to `daily`, `weekly`, `monthly`, or `yearly`.
- Set `interval` to 1 or greater.
- Use `byweekday` with daily or weekly schedules.
- Use `bysetpos` with `byweekday` for a monthly position.
- Use `count` to limit the total deliveries.
- Use `until_date` to set an end date.

Deliveries run on half-hour cycles at `:00` and `:30`.
Other minute values move delivery to the next cycle.

`start_date` can be in the past.
It anchors the recurrence.
The next delivery must be more than approximately 15 minutes in the future.

The server calculates `next_delivery_date`.
Do not send this read-only field.
Always check it after a create or schedule update.

## Access and API scopes

- Read operations require `subscription:read`.
- Write operations require `subscription:write`.
- AI prompt writes and test deliveries also require `query:read`.
- AI prompt operations also require viewer access to the query resource.
- Insight and dashboard subscriptions require viewer access to their saved resources.

Delivery history for an AI prompt report hides query-derived content from callers without query access.
The prompt and safe delivery errors remain visible.

## Plan limits

The free plan allows five non-deleted subscriptions per project.
A paid plan can set a different numeric limit or no numeric limit.

A deleted subscription frees one slot.
A paused subscription still uses one slot.

The limit applies across insight, dashboard, and AI prompt subscriptions.
If the plan limit blocks creation, delete an unused subscription or change the plan.

## AI requirements and billing

AI prompt reports require all these conditions at creation:

- PostHog Cloud, unless the instance runs in development mode.
- Organization approval for AI data processing.
- AI subscriptions enabled for the current user.
- `subscription:write` and `query:read` scopes.
- Viewer access to the query resource.

AI prompt reports use billable model calls.
The planner can use more than one model call to select events, create queries, repair queries, and write the report.
AI credits do not block creation.
PostHog checks the credit balance before report generation.
Use `understanding-billing-usage` to investigate `ai_credits_used_in_period`.

If the organization exhausts AI credits, PostHog skips the prompt report.
The subscription stays enabled.
PostHog moves its next delivery past the credit reset date.
PostHog can notify the active creator once during that billing period.

AI summaries on insight and dashboard snapshots also use AI credits.
Enabling one requires organization approval for AI data processing.
It also requires available AI credits and an available active-summary slot.

The active-summary limit applies across all projects in the organization.
The exact limit depends on the plan.

If credits run out after setup, PostHog skips the summary.
PostHog still sends the insight or dashboard snapshot.

## Test delivery

A test delivery sends a real message and creates a delivery record.
It uses the same delivery pipeline as a scheduled delivery.

Creation defaults `send_test_now` to `true`.
Set it to `false` unless the user approves an immediate delivery.

An update can also send immediately after these changes:

- The recipient or destination changes.
- The source insight, dashboard, tile selection, or prompt changes.
- The prompt report display options change.
- The subscription resumes.

Set `send_test_now: false` to suppress this immediate update delivery.
A schedule-only or title-only update does not send by default.

- The request returns `202` when PostHog queues the test.
- The request returns `409` when the subscription is disabled.
- The request returns `409` when another test for that subscription is active.
- The team limit is 10 test deliveries per minute.

Manual tests do not change the recurring schedule.
For `since_last_sent` AI windows, manual tests do not move the analysis anchor.

## Delivery history

Delivery history uses cursor pagination with 50 rows per page.
The newest delivery appears first.

Each delivery records these details:

- Trigger type: scheduled, manual, or target change.
- Status: starting, completed, failed, or skipped.
- Scheduled, created, updated, and finished times.
- The safe destination snapshot.
- Per-recipient status.
- Exported asset IDs.
- AI summary or AI prompt report fields when applicable.

Treat each stage as a separate check:

1. The API accepts and returns the configuration.
2. PostHog queues a delivery.
3. The delivery reaches a terminal state.
4. The user confirms external receipt when that proof is required.

Do not report success after only the first or second stage.
MCP hides per-recipient results, so it cannot prove success for each recipient.

The list tool omits large report content and sensitive error payloads.
Use the retrieve tool for one AI prompt report and its prompt snapshot.
The MCP retrieve tool still omits query diagnostics and sensitive recipient data.

## Failure and retry behavior

Transient failures retry inside the delivery run.
Examples include a temporary network error, an email service error, or a Slack rate limit.

A transient failure does not disable the subscription.
The next scheduled delivery still runs.

Permanent failures can automatically disable a subscription.
Examples include these conditions:

- A Slack integration is disconnected.
- Slack channel or file permissions are revoked.
- Microsoft Teams stops accepting the webhook.
- An AI prompt or its original creator becomes invalid.
- The organization revokes AI data processing approval.

PostHog sends the creator an in-app notification when possible.
PostHog can also send a notification email.

Fix the permanent cause before you resume the subscription.
An AI prompt subscription cannot resume if its original creator is unavailable.
Create a new subscription under an active user in that case.

## Ownership changes

The subscription creator owns failure and automatic-disable notifications.
PostHog sends them only while the creator remains an active organization member.

An AI prompt report requires its original creator for query access and report generation.
If that creator becomes unavailable, PostHog can automatically disable the subscription.
Recreate it under an active user.

Insight and dashboard subscriptions can continue without an active creator.
However, no former member receives their failure notifications.
Review ownership when a subscription owner leaves the organization.

## Delete, pause, and expiration

- Pause with `enabled: false` when the user might resume later.
- Resume with `enabled: true` after you fix any permanent failure.
- Delete with `posthog:subscriptions-delete` when the user wants all future delivery to stop.

The MCP delete action is a one-way soft delete.
An expired `count` or `until_date` produces no next delivery.
Extend or remove the end condition before you resume an expired schedule.
