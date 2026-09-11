---
name: managing-subscriptions
description: >
  Manage scheduled PostHog subscriptions for insight or dashboard snapshots.
  Use when a user wants recurring email, Slack, or Microsoft Teams delivery,
  wants an AI summary attached to a snapshot, wants to list or change existing
  subscriptions, wants to test or inspect a delivery, or wants to stop updates.
  Use product alerts instead when the user wants a notification only after a
  threshold or anomaly condition occurs.
---

# Managing subscriptions

Subscriptions send insight or dashboard snapshots on a fixed schedule.
They can send every delivery through email, Slack, or Microsoft Teams.

## Choose the correct product

- Use a subscription for a fixed schedule, such as "send this dashboard each Monday."
- Use a product alert for a data condition, such as "notify me when conversion drops below 10%."
- Use `creating-ai-subscription` for a recurring report that starts from a free-text prompt.
- Use an insight or dashboard subscription when the user already has the required charts.

An insight or dashboard subscription can include an AI summary.
The snapshot contains the saved chart results.
The AI summary can interpret those results, but its text can contain an incorrect number.

## Tools

| Tool | Purpose |
| --- | --- |
| `posthog:subscriptions-list` | Find existing subscriptions |
| `posthog:subscriptions-retrieve` | Read one subscription |
| `posthog:subscriptions-create` | Create a subscription |
| `posthog:subscriptions-partial-update` | Change a subscription or set its enabled state |
| `posthog:subscriptions-test-delivery-create` | Send an immediate test delivery |
| `posthog:subscriptions-deliveries-list` | Check delivery attempts |
| `posthog:subscriptions-deliveries-retrieve` | Read one delivery and its AI report |
| `posthog:subscriptions-delete` | Stop all future deliveries |
| `posthog:integrations-list` | Find a Slack integration |
| `posthog:integrations-channels-retrieve` | Find Slack channel IDs and names |
| `posthog:dashboard-get` | Read dashboard tiles |
| `posthog:insight-get` | Resolve an insight short ID or URL |

## Create a subscription

### 1. Check for an existing subscription

Call `posthog:subscriptions-list` before you create a subscription.
Use `search` when the user supplied a title, insight name, or dashboard name.

If a matching subscription exists, offer to update it.
Do not create a duplicate without the user's approval.

A Teams result contains only the webhook host.
One host can serve many channels.
Do not use this host to identify a duplicate.
Show the title, schedule, creator, and creation date for each possible match.
Ask the user to select a subscription when these fields identify it.
Create a new subscription when no field identifies the correct channel.

### 2. Resolve the resource

- For an insight, resolve its numeric ID with `posthog:insight-get` when necessary.
- For a dashboard, call `posthog:dashboard-get` and identify the required tiles.
- A dashboard subscription requires 1 to 10 IDs in `dashboard_export_insights`.
- Ask which tiles to include when the user did not specify them.

Set only `insight` or `dashboard`.
The API derives the read-only `resource_type` from this field.
The resource type cannot change after creation.

### 3. Resolve the delivery target

Use the target that the user requested.
Ask for a target when the request does not contain one.

#### Email

- Set `target_type` to `email`.
- Set `target_value` to the comma-separated recipient addresses.

#### Slack

1. Call `posthog:integrations-list` and find an integration with `kind: slack`.
2. Call `posthog:integrations-channels-retrieve` for that integration.
3. Set `integration_id` to the integration ID.
4. Set `target_value` to `<channel_id>|<channel_name>`.

If Slack is not connected, ask the user to connect it in Project settings > Integrations.
Offer email as an alternative.

#### Microsoft Teams

- Ask the user to add the Workflows app to the target channel.
- Ask them to select the workflow that posts to a channel after a webhook request.
- Set `target_type` to `teams`.
- Set `target_value` to the full Microsoft Teams webhook URL.
- Treat the webhook URL as a secret.
- Do not repeat it in a response.

The API returns only the webhook host.
The returned value cannot replace the saved webhook URL.

### 4. Set the schedule

- Set `frequency` to `daily`, `weekly`, `monthly`, or `yearly`.
- Set `interval` to the number of frequency periods between deliveries.
- Use `byweekday` for selected weekdays.
- Use `bysetpos` with `byweekday` for schedules such as the last Monday of each month.
- Use `count` or `until_date` when the user requests an end condition.
- Set `start_date` to an ISO 8601 date and time.

Deliveries run on half-hour cycles at `:00` and `:30`.
Use one of these minute values when you set `start_date`.
Keep the user's time zone explicit when you convert the requested time.

### 5. Ask about an AI summary

Before creation, ask if the user wants an AI summary.
Do not enable it without approval.

If the user approves it:

- Set `summary_enabled` to `true`.
- Offer `summary_prompt_guide` for a custom focus.
- Explain that AI data processing approval and available AI credit are required.

These fields apply only to insight and dashboard subscriptions.

### 6. Create and check

Call `posthog:subscriptions-create` with the resolved values.
Then call `posthog:subscriptions-retrieve` or `posthog:subscriptions-list`.

Check these results:

- The resource and target match the request.
- `enabled` is `true`.
- `next_delivery_date` matches the requested schedule.
- The AI summary setting matches the user's choice.

Offer a test delivery when the target or format needs confirmation.

## Example requests

### Weekly dashboard email

```yaml
dashboard: 67
dashboard_export_insights: [101, 102, 103]
target_type: email
target_value: product-team@example.com
frequency: weekly
interval: 1
byweekday: [monday]
start_date: '2026-09-14T09:00:00Z'
summary_enabled: false
```

### Daily Slack insight with an AI summary

```yaml
insight: 12345
target_type: slack
target_value: 'C0123456789|product-updates'
integration_id: 42
frequency: daily
interval: 1
start_date: '2026-09-15T09:30:00Z'
summary_enabled: true
summary_prompt_guide: 'Focus on conversion changes and unusual results.'
```

## Change a subscription

Call `posthog:subscriptions-partial-update` with the subscription ID.

- Set `enabled: false` to pause deliveries.
- Set `enabled: true` to resume deliveries.
- Send the complete new target when you change recipients.
- Send both `target_type` and `target_value` when you change the delivery type.
- Omit `target_value` to keep an existing Microsoft Teams webhook URL.
- Use `summary_enabled` and `summary_prompt_guide` to change the AI summary.

Do not try to change the subscription resource type.
Create a new subscription for a different resource type.

## Test and inspect delivery

1. Call `posthog:subscriptions-test-delivery-create` with the subscription ID.
2. Call `posthog:subscriptions-deliveries-list` until the new delivery finishes.
3. Call `posthog:subscriptions-deliveries-retrieve` when you need one delivery's report.

The test sends a real message to the configured target.
Ask for approval before you send it unless the user already requested a test.

The test tool returns `409` when a test is active or the subscription is disabled.
Resume a paused subscription before you test it.

## Stop a subscription

Call `posthog:subscriptions-delete` with the subscription ID.
Deletion stops all future deliveries.
The MCP tools cannot restore a deleted subscription.

Confirm the target subscription before deletion.
Ask for approval unless the user already requested deletion or unsubscribe.

## Handle failures

- For a failed create or update, report the API error and the required next action.
- For Slack errors, check the integration and channel access.
- For Microsoft Teams errors, ask the user to create a new URL with the correct workflow.
- For generic webhook requests, explain that subscriptions support only email, Slack, and Microsoft Teams.
- For schedule errors, check `start_date`, `frequency`, `interval`, and recurrence fields together.
- For AI summary errors, check AI data processing approval, the summary limit, and AI credit.
- For send errors, inspect delivery history before you change the subscription.

## Related skills

- `building-a-dashboard`: Create the dashboard before you subscribe to it.
- `creating-ai-subscription`: Schedule a report from a free-text AI prompt.
- `adding-product-alerting`: Notify users only when data meets a condition.
