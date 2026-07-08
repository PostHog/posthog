---
name: creating-ai-subscription
description: >
  Create a recurring AI-generated PostHog report — schedule a free-text prompt to
  run on a cron, with the LLM-synthesized markdown delivered to email or Slack on
  each tick. Use when the user wants a recurring AI summary of X on any cadence
  (daily, weekly, monthly, yearly) rather than a one-off report. (To attach an AI
  summary to an existing insight/dashboard
  subscription instead of a free-text prompt, see `managing-subscriptions` and its
  `summary_enabled` option.)
---

# Creating a prompt subscription

## When to use this

A **subscription** delivers a PostHog report to email or Slack on a recurring
schedule. There are three kinds, distinguished by which field you set — the kind is
derived and returned as the read-only `resource_type`:

- **`insight`** — periodic snapshots of one existing insight (`resource_type: "insight"`)
- **`dashboard`** — periodic snapshots of a dashboard's tiles (`resource_type: "dashboard"`)
- **`prompt`** — a recurring **AI-generated** report from a free-text prompt: an LLM
  plans and runs HogQL over the project's data and synthesizes a fresh markdown report
  each tick (`resource_type: "ai_prompt"`)

Use **this** skill for the **prompt** kind — i.e. when the user wants a recurring AI
summary of X (on any cadence — daily, weekly, monthly, yearly) rather than a recurring
snapshot of one existing insight/dashboard, or a single one-off report. Pick a prompt subscription when the
value is the _analysis itself_ (the LLM deciding what to query and writing it up),
not a fixed chart they already built. For an insight/dashboard subscription, set
`insight`/`dashboard` instead of `prompt` and the AI gates below don't apply.

This skill covers **creating** the subscription. Once it exists you manage its
lifecycle with the same `subscriptions-*` tools (see below): list it, edit/disable/
re-enable it, send a test delivery, or delete it.

## Tools

| Tool                                         | Purpose                                             |
| -------------------------------------------- | --------------------------------------------------- |
| `posthog:subscriptions-create`               | Create the recurring prompt subscription            |
| `posthog:subscriptions-list`                 | Confirm it landed; inspect existing subscriptions   |
| `posthog:subscriptions-partial-update`       | Edit, disable (`enabled: false`), or re-enable it   |
| `posthog:subscriptions-test-delivery-create` | Send an immediate test delivery to its target(s)    |
| `posthog:subscriptions-delete`               | Soft-delete it (stops all future deliveries)        |
| `posthog:integrations-list`                  | Find a Slack `integration_id` (filter `kind=slack`) |
| `posthog:integrations-channels-retrieve`     | List a Slack integration's channels (id + name)     |

## What you need before calling

The endpoint enforces three create-time gates and will return 400 if any fails:

1. **PostHog Cloud, or `DEBUG=true`** — self-hosted production deployments are not
   eligible (the LLM call routes through a PostHog-managed key).
2. **Org-level "AI data processing approved"** — must be toggled on in
   `Org settings → Data → AI data processing`. The user must opt in to AI features
   for the organization first.
3. **Prompt subscriptions enabled** for the organization — a PostHog-managed rollout
   flag. If it's off, the org has not been granted access yet; tell the user to
   reach out to PostHog to enable it (there is no self-serve toggle).

If any of the three is missing, stop and tell the user which one to fix —
re-calling the tool will not help.

Your access token also needs the **`query:read`** scope in addition to
`subscription:write`: a prompt subscription runs LLM-generated HogQL over the project's
data, so the backend requires query access to create, edit/re-enable, test-deliver,
or delete one. A `subscription:write`-only token is rejected with a 403.

## Required arguments

```yaml
prompt: "..."                         # ≤4000 chars; setting this (with no insight/dashboard) makes it a prompt sub → resource_type "ai_prompt"
target_type: "email" | "slack"        # webhook is rejected for prompt subs
target_value: "..."                   # comma-separated emails, or "<channel_id>|<channel_name>"
frequency: "daily" | "weekly" | "monthly" | "yearly"
interval: 1                            # 1 = every tick; 2 = every other tick; etc.
start_date: "2026-09-15T09:00:00Z"   # anchors the recurrence + time-of-day; need not be in the future — the scheduler delivers the next occurrence
title: "..."                          # display name in the subscriptions list
```

There is no `resource_type` argument to send — the kind is **derived**
from which field you set (`prompt` ⇒ AI report) and returned as the read-only `resource_type`.

## Optional arguments

```yaml
byweekday: ['monday', 'wednesday'] # weekly only — days the rrule fires
bysetpos: 1 # most useful with monthly; requires byweekday — e.g. byweekday:['monday']+bysetpos:-1 = last Monday
count: 10 # cap total deliveries
until_date: '2026-12-31T00:00:00Z' # stop on/before this date
integration_id: 42 # Slack only — required; from integrations-list (see "Slack target")
```

## Slack target

`target_value` must be `<channel_id>|<channel_name>` (the format the integration
returns). Build it in three steps:

1. `posthog:integrations-list` filtered by `kind=slack` → pick the Slack
   integration's `id`.
2. `posthog:integrations-channels-retrieve` with that `id` → pick a channel; it
   returns each channel's `id` and `name`, which you assemble into `target_value`
   as `<id>|<name>`.
3. Pass that integration's `id` as `integration_id` — the subscription is pinned
   to one specific Slack integration so reconnections elsewhere don't accidentally
   re-route deliveries.

## Examples

### Weekly Monday-morning AI summary by email

```yaml
prompt: 'Top events week over week, with the biggest drops and any new failure modes called out.'
target_type: email
target_value: founders@acme.example
frequency: weekly
interval: 1
byweekday: ['monday']
start_date: '2026-09-14T08:00:00Z'
title: 'Weekly product pulse'
```

### Daily Slack report at 9am

```yaml
prompt: "Yesterday's sign-ups, where they came from, and any errors they hit during onboarding."
target_type: slack
target_value: 'C0123456789|growth-updates' # <channel_id>|<channel_name>; only the channel id is used, the name is cosmetic
integration_id: 42
frequency: daily
interval: 1
start_date: '2026-09-15T09:00:00Z'
title: 'Daily onboarding watch'
```

## Pitfalls

- **The kind is immutable.** It's derived from which relation is set, so you can't flip an
  insight or dashboard sub into a prompt sub after the fact (or vice versa) — a PATCH that adds a
  `prompt` to an insight sub is rejected. Pick the right kind at create time.
- **Re-enabling a previously auto-disabled prompt sub** has two preconditions, both
  enforced on the PATCH: (1) a valid `prompt` — already persisted on the row, or a
  new one in the PATCH body (so bare `{"enabled": true}` works when the stored prompt
  is still valid, but is rejected when the disable cause was an invalid prompt until
  you supply a good one); and (2) the **original creator is still an active user** —
  if that account was deactivated the sub cannot be re-enabled at all (no prompt will
  help; re-create it instead).
- **`next_delivery_date` is server-computed from the rrule.** Don't try to set it
  manually — it's read-only. The first delivery fires at the first `start_date`
  occurrence that is at least a short buffer (currently ~15 minutes) in the future,
  so a `start_date` only seconds ahead rolls to the next occurrence.
- **Transient send failures retry; only permanent failures auto-disable.** A
  transient failure (Slack rate limit, SMTP blip, network) fails that delivery and
  is retried by Temporal within the run, then re-fires on the next scheduled tick —
  it does **not** auto-disable the subscription, so a persistently-failing channel
  will keep retrying every tick until you fix it. Only permanent/structural causes
  auto-disable: a disconnected Slack integration, a revoked channel permission, an
  invalid prompt, or revoked AI data-processing consent. (For multi-recipient email,
  a delivery only fails when _every_ recipient fails; partial successes still send.)
  Within a single delivery run the rendered markdown is cached, so Temporal retries
  of that run don't re-run the LLM pipeline — but each new scheduled tick generates a
  fresh report.

## After it lands

`subscriptions-list` will return the new row. Confirm `resource_type: "ai_prompt"`,
`enabled: true`, `next_delivery_date` is in the future, and `prompt` matches what
you sent. The first scheduled tick will run the planner → HogQL → synthesis
pipeline and email/Slack the rendered markdown.
