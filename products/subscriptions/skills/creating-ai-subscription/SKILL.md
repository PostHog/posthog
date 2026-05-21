---
name: creating-ai-subscription
description: >
  Create a recurring AI-generated PostHog report — schedule a free-text prompt to
  run on a cron, with the LLM-synthesized markdown delivered to email or Slack on
  each tick. Use when the user wants "send me a weekly AI summary of X" rather than
  a one-off report.
---

# Creating an AI subscription

Use this skill when the user wants a **recurring** AI-generated report delivered on
a schedule. For a one-off "generate now and return markdown" (no schedule, no
delivery), use `generating-ad-hoc-ai-report` instead.

## Tools

| Tool                           | Purpose                                           |
| ------------------------------ | ------------------------------------------------- |
| `posthog:subscriptions-create` | Create the recurring AI subscription              |
| `posthog:subscriptions-list`   | Confirm it landed; inspect existing subscriptions |
| `posthog:integrations-list`    | Find a Slack `integration_id` when needed         |

## What you need before calling

The endpoint enforces three create-time gates and will return 400 if any fails:

1. **PostHog Cloud, or `DEBUG=true`** — self-hosted production deployments are not
   eligible (the LLM call routes through a PostHog-managed key).
2. **Org-level "AI data processing approved"** — must be toggled on in
   `Org settings → Data → AI data processing`. The user must opt in to AI features
   for the organization first.
3. **`SUBSCRIPTION_AI_PROMPT` feature flag enabled** for the organization.

If any of the three is missing, stop and tell the user which one to fix —
re-calling the tool will not help.

## Required arguments

```yaml
content_type: "ai_prompt"            # discriminator — pinned for the lifetime of the sub
prompt: "..."                         # ≤4000 chars; what the LLM should report on
target_type: "email" | "slack"        # webhook is rejected for AI subs
target_value: "..."                   # comma-separated emails, or "<channel_id>|<channel_name>"
frequency: "daily" | "weekly" | "monthly" | "yearly"
interval: 1                            # 1 = every tick; 2 = every other tick; etc.
start_date: "2026-01-15T09:00:00Z"   # first delivery, also defines time-of-day
title: "..."                          # display name in the subscriptions list
```

## Optional arguments

```yaml
byweekday: ['monday', 'wednesday'] # weekly only — days the rrule fires
bysetpos: 1 # monthly only — 1=first, 2=second, -1=last
count: 10 # cap total deliveries
until_date: '2026-12-31T00:00:00Z' # stop on/before this date
ai_config: # rarely needed; whitelisted only
  model: 'gpt-4.1-mini' # synthesis model
  planner_model: 'gpt-4.1-mini' # planner model
integration_id: 42 # required when target_type is "slack"
```

## Slack target

`target_value` must be `<channel_id>|<channel_name>` (the format the integration
returns). Look up an integration with `posthog:integrations-list` filtered by
`kind=slack`, then pick a channel from that integration. Pass that integration's
ID as `integration_id` — the subscription is pinned to one specific Slack
integration so reconnections elsewhere don't accidentally re-route deliveries.

## Examples

### Weekly Monday-morning AI summary by email

```yaml
content_type: ai_prompt
prompt: 'Top events week over week, with the biggest drops and any new failure modes called out.'
target_type: email
target_value: founders@acme.example
frequency: weekly
interval: 1
byweekday: ['monday']
start_date: '2026-01-19T08:00:00Z'
title: 'Weekly product pulse'
```

### Daily Slack report at 9am

```yaml
content_type: ai_prompt
prompt: "Yesterday's sign-ups, where they came from, and any errors they hit during onboarding."
target_type: slack
target_value: 'C0123456789|#growth-updates'
integration_id: 42
frequency: daily
interval: 1
start_date: '2026-01-15T09:00:00Z'
title: 'Daily onboarding watch'
```

## Pitfalls

- **`content_type` is immutable.** You can't flip an insight or dashboard sub
  into an AI sub after the fact, and vice versa. Pick the right kind at create time.
- **Re-enabling a previously auto-disabled AI sub** requires either a valid `prompt`
  already persisted on the row, or a new `prompt` in the PATCH body — bare
  `{"enabled": true}` is rejected until the underlying prompt issue is fixed.
- **`next_delivery_date` is server-computed from the rrule.** Don't try to set it
  manually — it's read-only. The first delivery fires at the first `start_date`
  occurrence that is at least 15 minutes in the future.
- **One transient send failure auto-fails the whole delivery** (the cached markdown
  means a retry is cheap). Slack rate limits or SMTP blips will trigger Temporal
  retries on the next tick; persistent failures auto-disable the subscription.
- **Test the prompt first with `generating-ad-hoc-ai-report`** before scheduling
  it — much faster feedback than waiting for the next cron tick.

## After it lands

`subscriptions-list` will return the new row. Confirm `content_type: "ai_prompt"`,
`enabled: true`, `next_delivery_date` is in the future, and `prompt` matches what
you sent. The first scheduled tick will run the planner → HogQL → synthesis
pipeline and email/Slack the rendered markdown.
