---
name: managing-subscriptions
description: >
  Create and manage scheduled PostHog subscriptions for insight snapshots,
  dashboard snapshots, and AI prompt reports. Use when a user wants recurring
  email, Slack, or Microsoft Teams delivery; an AI summary; delivery history;
  schedule or recipient changes; a test delivery; pause, resume, or deletion;
  or help with subscription permissions, limits, billing, and failures. Use
  product alerts when delivery must depend on a threshold or anomaly.
---

# Managing subscriptions

Subscriptions deliver product data on a fixed schedule.
They support insight snapshots, dashboard snapshots, and AI prompt reports.

## Read the relevant references

- Read [subscription-types.md](references/subscription-types.md) before you select or change a resource type.
- Read [destinations.md](references/destinations.md) before you create or change a destination.
- Read [operations.md](references/operations.md) for schedules, limits, billing, delivery checks, and failures.
- Use `creating-ai-subscription` for the detailed prompt report creation workflow.

## Choose the correct product

- Use a subscription for fixed delivery, such as "send this dashboard every Monday."
- Use a product alert for a condition, such as "notify me when conversion falls below 10%."
- Use a reminder when the user wants a private prompt to inspect a resource later.
- Use a Signals scout when an agent must decide what is important to report.

Subscriptions do not evaluate thresholds, recovery, consecutive breaches, or quiet hours.
Snapshot subscriptions attempt each scheduled occurrence even when the saved results do not change.

## Tools

| Tool | Purpose |
| --- | --- |
| `posthog:subscriptions-list` | Find subscriptions |
| `posthog:subscriptions-retrieve` | Read one subscription |
| `posthog:subscriptions-create` | Create a subscription |
| `posthog:subscriptions-partial-update` | Change, pause, or resume a subscription |
| `posthog:subscriptions-test-delivery-create` | Send a test delivery |
| `posthog:subscriptions-deliveries-list` | List delivery attempts |
| `posthog:subscriptions-deliveries-retrieve` | Read one delivery |
| `posthog:subscriptions-delete` | Stop all future deliveries |
| `posthog:integrations-list` | Find a Slack integration |
| `posthog:integrations-channels-retrieve` | Find Slack channels |
| `posthog:dashboard-get` | Read dashboard tiles |
| `posthog:insight-get` | Resolve an insight ID |

## Create a subscription

1. Call `posthog:subscriptions-list` and check for a duplicate.
2. Select one resource type from [subscription-types.md](references/subscription-types.md).
3. Resolve the destination with [destinations.md](references/destinations.md).
4. Resolve the schedule with [operations.md](references/operations.md).
5. Ask whether the user wants an immediate delivery.
6. Set `send_test_now` to the user's choice.
7. Call `posthog:subscriptions-create`.
8. Read the saved subscription and check each requested field.
9. If the user approved an immediate delivery, check its delivery record.

Do not infer missing recipients, channels, times, or time zones.
Ask for these values before creation.

### Find existing subscriptions

Use these list filters when they reduce ambiguity:

- `resource_type`: `insight`, `dashboard`, or `ai_prompt`.
- `target_type`: `email`, `slack`, or `teams`.
- `insight` or `insights`: One insight ID or a comma-separated ID list.
- `dashboard`: One dashboard ID.
- `dashboard_tiles`: Insight subscriptions for live tiles on one dashboard.
- `created_by`: One creator UUID.
- `deleted`: Include or select soft-deleted subscriptions.

### Check for duplicates

Use `search` when the user supplied a title, insight name, or dashboard name.
Prompt subscriptions match their title, not their prompt text.
Compare the resource, destination type, target, schedule, and enabled state.

A Teams result contains only the webhook host.
One host can serve many channels.
Do not use the host to identify a duplicate.

Show the title, schedule, creator, and creation date for possible Teams matches.
Ask the user to select a subscription when these fields identify it.
Create a new subscription when no field identifies the target channel.

### Confirm the saved result

Check these fields after creation:

- `resource_type` matches `insight`, `dashboard`, or `ai_prompt`.
- `target_type` and the safe target label match the request.
- `enabled` is `true`.
- `next_delivery_date` matches the schedule and time zone.
- The AI and delivery options match the user's choices.

## Change a subscription

Call `posthog:subscriptions-retrieve` before each update.
Then call `posthog:subscriptions-partial-update` with the changed fields.

Ask before an update that can send an immediate delivery.
Set `send_test_now: false` when the user does not approve that delivery.

- Set `enabled: false` to pause delivery.
- Set `enabled: true` to resume delivery.
- Send the complete new target when you change recipients.
- Send `target_type` and `target_value` together when you change the destination type.
- Omit `target_value` to keep a saved Teams webhook URL.
- Send the full new Teams webhook URL when you replace it.

The resource type cannot change.
Create a new subscription when the user wants a different resource type.

Check the new `next_delivery_date` after a schedule update.
An exhausted schedule cannot resume until the user extends or removes its end condition.

## Test and inspect delivery

1. Ask for approval unless the user already requested a test.
2. Call `posthog:subscriptions-test-delivery-create`.
3. Poll `posthog:subscriptions-deliveries-list` for the new manual delivery.
4. Read the delivery when the list result needs more detail.

A test sends a real message.
The tool returns `202` after it queues the delivery.
It returns `409` when another test is active or the subscription is disabled.

Delivery states are `starting`, `completed`, `failed`, and `skipped`.
Filter the delivery list by `status` when you investigate a failure.
A queued workflow does not prove delivery.
A completed delivery can contain partial recipient failures.
The MCP tools hide per-recipient results.
Do not claim that each recipient succeeded.

## Stop a subscription

Confirm the subscription ID and safe destination label.
Ask for approval unless the user already requested deletion or unsubscribe.
Then call `posthog:subscriptions-delete`.

Deletion is a one-way soft delete through MCP.
It stops future deliveries and frees a plan slot.
Create a new subscription if the user needs it again.

## Report the result

- State the resource type, destination type, schedule, and next delivery date.
- State whether the subscription is enabled.
- State whether AI features can consume AI credits.
- Do not repeat email addresses unless the user needs them for confirmation.
- Never repeat a Teams webhook URL.

## Related skills

- `creating-ai-subscription`: Create a report from a free-text AI prompt.
- `building-a-dashboard`: Create a dashboard before you subscribe to it.
- `adding-product-alerting`: Notify users when data meets a condition.
- `managing-reminders`: Schedule a private prompt to inspect a resource.
- `understanding-billing-usage`: Investigate PostHog AI credit use.
