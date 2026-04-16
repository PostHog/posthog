---
name: managing-subscriptions
description: 'Manage PostHog subscriptions — scheduled email, Slack, or webhook deliveries of insight or dashboard snapshots. Use when the user wants to subscribe to an insight or dashboard, check existing subscriptions, change delivery frequency, add or remove recipients, or stop receiving updates.'
---

# Managing subscriptions

This skill guides you through managing PostHog subscriptions.
Subscriptions deliver scheduled snapshots of insights or dashboards via email, Slack, or webhook.

## When to use this skill

Use this skill when the user:

- Wants to "track", "follow", "subscribe to", or "get updates" about an insight or dashboard
- Asks for "daily updates", "weekly reports", or "send me this every morning"
- Wants to know what subscriptions they have
- Asks to stop, pause, or unsubscribe from something
- Wants to change who receives an update or how often

## Subscriptions vs alerts

Subscriptions and alerts serve different purposes:

- **Subscriptions** deliver a snapshot on a fixed schedule (daily, weekly, etc.) regardless of the data
- **Alerts** fire only when a condition is met (threshold crossed, anomaly detected)

If the user says "notify me when this drops below 100", use alerts.
If the user says "send me this every morning", use subscriptions.

## Workflow

### Listing existing subscriptions

Before creating a new subscription, check if one already exists.

Use `subscriptions-list` with optional filters:

- Filter by insight: pass the `insight` query parameter with the insight ID
- Filter by dashboard: pass the `dashboard` query parameter with the dashboard ID
- Filter by channel: pass `target_type` as `email`, `slack`, or `webhook`

### Creating a subscription

#### Step 1: Ask the user how they want to receive it

**Always ask the user whether they want email or Slack delivery** before creating a subscription.
Do not assume a channel — ask explicitly:

> Would you like to receive this via **email** or **Slack**?

If the user says Slack, you must verify the integration is available (see step 2).
If the user doesn't have a preference, suggest email as the simplest option.

#### Step 2: Verify channel availability

**Email** requires no setup — it works out of the box. You just need the user's email address.
Get it from the user context or from `org-members-list`.

**Slack** requires a connected Slack integration. Before creating a Slack subscription:

1. Call `integrations-list` and look for an integration where `kind` is `"slack"`
2. If a Slack integration exists, note its `id` — you'll need it as `integration_id`
3. If **no Slack integration exists**, tell the user:
   > Slack isn't connected to this project yet. You can set it up in
   > [Project settings > Integrations](/settings/integrations).
   > In the meantime, would you like to receive this via email instead?

Slack setup requires an OAuth flow in the browser — it cannot be done via MCP.

**Webhook** requires the user to provide a URL. Verify it looks like a valid URL before submitting.

#### Step 3: Identify the target

Get the insight ID or dashboard ID. If the user provides a URL like `/project/2/insights/pKxzopBG`,
fetch the insight first with `insight-get` to get the numeric ID.

#### Step 4: Determine delivery settings from the user's request

| User says                               | Parameters                                                                |
| --------------------------------------- | ------------------------------------------------------------------------- |
| "every day" / "daily" / "every morning" | `frequency: "daily"`                                                      |
| "every week" / "weekly"                 | `frequency: "weekly"`                                                     |
| "every Monday"                          | `frequency: "weekly"`, `byweekday: ["monday"]`                            |
| "every month" / "monthly"               | `frequency: "monthly"`                                                    |
| "twice a week"                          | `frequency: "weekly"`, `interval: 1`, `byweekday: ["monday", "thursday"]` |

#### Step 5: Create with `subscriptions-create`

For an insight subscription via email:

```json
{
  "insight": 12345,
  "target_type": "email",
  "target_value": "user@example.com",
  "frequency": "daily",
  "start_date": "2025-01-01T09:00:00Z"
}
```

For a dashboard subscription (requires selecting which insights to include, max 6):

```json
{
  "dashboard": 67,
  "dashboard_export_insights": [101, 102, 103],
  "target_type": "email",
  "target_value": "user@example.com",
  "frequency": "weekly",
  "byweekday": ["monday"],
  "start_date": "2025-01-01T09:00:00Z"
}
```

For Slack delivery, include the `integration_id` from step 2:

```json
{
  "insight": 12345,
  "target_type": "slack",
  "target_value": "#general",
  "integration_id": 789,
  "frequency": "daily",
  "start_date": "2025-01-01T09:00:00Z"
}
```

### Updating a subscription

Use `subscriptions-partial-update` with the subscription ID. Common updates:

- **Change frequency**: `{"frequency": "weekly", "byweekday": ["monday"]}`
- **Add recipients**: Update `target_value` with the full comma-separated list
- **Change channel**: Update `target_type` and `target_value` together

### Deactivating a subscription

Subscriptions are soft-deleted. Use `subscriptions-partial-update`:

```json
{
  "id": 456,
  "deleted": true
}
```

## Defaults

When the user doesn't specify details:

- **Frequency**: `"daily"`
- **Channel**: email to the current user
- **Start date**: now (ISO 8601)
- **Title**: auto-generated from the insight/dashboard name if not specified

## Error handling

- **Duplicate check**: If a subscription already exists for the same insight/dashboard and channel, inform the user and offer to update it rather than creating a duplicate
- **Slack not connected**: If a Slack subscription is requested but no Slack integration exists, explain that Slack must be connected in [Project settings > Integrations](/settings/integrations) first, then offer email as an alternative. Do not attempt to create the subscription — it will fail with a validation error
- **Slack integration wrong team**: The Slack integration must belong to the same PostHog team. If `integrations-list` returns Slack integrations but creation still fails, the integration may be misconfigured
- **Dashboard insights**: Dashboard subscriptions require at least 1 and at most 6 insights selected via `dashboard_export_insights`. If the user doesn't specify which insights, fetch the dashboard with `dashboard-get` and select the first 6 insights from its tiles
