---
name: authoring-error-tracking-alerts
description: >
  Author error tracking alerts that fire when an issue is created, reopened, or starts spiking. Use when
  the user asks to set up error notifications, route exceptions to Slack/webhook/Linear, or evaluate which
  error events are worth alerting on. Covers trigger-event selection, integration choice, dedup against
  existing alerts, and shipping with the canonical message body shape.
---

# Authoring error tracking alerts

Authoring an error tracking alert is a _routing_ problem, not a measurement problem. The trigger events
already exist and fire on real conditions in the ingestion pipeline — your job is to pick the right
trigger for the user's intent, dedupe against what's already configured, and wire a destination they can
actually act on.

## When to use this skill

- The user asks to set up alerts / notifications for errors or exceptions in their project.
- The user wants a starter set of alerts after enabling error tracking.
- The user pastes an issue link and asks "notify me when this happens again" — usually `_reopened` with a
  per-issue property filter.

## When _not_ to use this skill

- Tuning the spike detector itself (multiplier, window, threshold). That lives behind the spike detection
  config endpoint and is not exposed via MCP today.
- Investigating an active incident — query the issue / its events directly via
  `posthog:query-error-tracking-issue` and `posthog:query-error-tracking-issue-events` instead of
  authoring more alerts mid-fire.
- Configuring volume-threshold alerts (count of `$exception` events over a window). That's a logs-style
  alert and is not in scope here — error tracking alerts ride the lifecycle events instead.

## Tools

| Tool                                           | Job                                                              | Where it fits                |
| ---------------------------------------------- | ---------------------------------------------------------------- | ---------------------------- |
| `posthog:error-tracking-alerts-list`           | List existing alerts; dedupe before creating.                    | Step 2 — dedupe.             |
| `posthog:integrations-list`                    | Find the user's Slack workspace id (filter by `kind=slack`).     | Step 3 — pick channel.       |
| `posthog:integrations-channels-retrieve`       | List Slack channels for a workspace.                             | Step 3 — pick channel.       |
| `posthog:error-tracking-alerts-create`         | Create the alert (HogFunction with `type=internal_destination`). | Step 4 — ship.               |
| `posthog:error-tracking-alerts-partial-update` | Toggle, rename, or modify an existing alert.                     | When tuning, not authoring.  |
| `posthog:error-tracking-alerts-delete`         | Soft-delete an alert.                                            | When the user says "remove". |

## Trigger events — pick exactly one per alert

There are three lifecycle events. Each has a different "noise vs urgency" trade-off — picking the wrong
one is the most common cause of alert fatigue here.

| Event                            | Fires when                                            | Use when                                                                                                                            |
| -------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `$error_tracking_issue_created`  | A brand-new issue first appears.                      | Small projects, or projects where every new error type is genuinely worth a look. Floods large/noisy projects.                      |
| `$error_tracking_issue_reopened` | A previously resolved issue starts emitting again.    | Catch regressions on issues someone already triaged. The safest "I want to know if this comes back" trigger.                        |
| `$error_tracking_issue_spiking`  | The spike detector flags abnormal volume on an issue. | Production projects with high baseline volume. Threshold/multiplier is shared across the project — check spike config before using. |

If the user is vague ("alert me on errors"), default to `_spiking`. It's the most signal-dense trigger
and the least likely to cause alert fatigue. Confirm explicitly before proceeding.

## Workflow

### 1. Confirm intent

You need three things from the user before creating anything:

- **Which trigger event.** If unspecified, recommend `_spiking` and ask for confirmation. Do not silently
  pick one.
- **Which channel.** Slack channel name, webhook URL, Linear team, etc. Never hardcode a production
  channel. If the user says "the dev channel", ask for the exact channel id or name.
- **Which scope.** All issues (most common), or scoped to a specific issue / exception type / assignee.

### 2. Dedupe against existing alerts

Call `posthog:error-tracking-alerts-list` with `type: ["internal_destination"]` and `limit: 1000` so the
scan covers **every** existing alert destination, not just the first page. The tool defaults to 100 rows
and paginates — on a large project the default page silently hides older alerts (for example, existing
`$error_tracking_issue_created` destinations), which leads to duplicate alerts. If a `next` cursor still
comes back, page through it until exhausted before deduping. Then filter the combined results
client-side by `filters.events[].id`.

- If an alert exists for the **same event** delivering to the **same channel**, stop. Tell the user it
  already exists and ask whether they want to change anything (in which case use
  `error-tracking-alerts-partial-update`) or skip.
- Multiple alerts on the same event for the same channel produce duplicate Slack messages — the user
  almost never wants this.
- Multiple alerts on the same event for **different** channels (e.g. one for `#oncall`, one for the
  oncall webhook) is fine and sometimes intentional. Confirm.

PostHog's "alerts configured" recommendation only inspects `filters.events` — adding per-issue
`filters.properties` does not affect the status the recommendations card reports.

### 3. Pick the integration

For Slack:

1. `posthog:integrations-list` with `kind=slack` → pick the integration `id` (an integer).
2. `posthog:integrations-channels-retrieve` with that id → pick the channel id (e.g. `C0123ABC`). Channel
   names like `"#oncall"` are accepted but channel ids are preferred — they survive renames.

For webhook: the user supplies a single `https://` URL. Refuse `http://` URLs.

For Linear / GitHub / GitLab: confirm the integration is connected via `posthog:integrations-list` first,
then ask the user which project / repository / team to file issues into.

### 4. Create the alert

Call `posthog:error-tracking-alerts-create` with:

```json
{
  "type": "internal_destination",
  "template_id": "template-slack",
  "name": "<short, channel-attributed name>",
  "enabled": true,
  "filters": {
    "events": [{ "id": "$error_tracking_issue_created", "type": "events" }]
  },
  "inputs": {
    "slack_workspace": { "value": <slack_integration_id_int> },
    "channel": { "value": "<channel_id>" },
    "text": { "value": "..." },
    "blocks": { "value": [...] }
  }
}
```

The canonical Slack `blocks` payload for each event lives in
[references/block-templates.md](./references/block-templates.md). Copy the matching block verbatim — it
matches the in-product alert wizard, so agent-created alerts look identical to UI-created ones.

For per-issue scoping — `created` / `reopened` only, spiking events carry no exception properties — add
to `filters`:

```json
"properties": [
  { "key": "$exception_issue_id", "value": "<issue_uuid>", "operator": "exact", "type": "event" }
]
```

Other useful property filters: `$exception_types` (exception class names, an array), `name` (issue
title). See [references/event-triggers.md](./references/event-triggers.md) for the full property surface
per event.

### 5. Verify

Echo the alert back to the user with: name, trigger event (human-readable), destination, and a one-line
preview of the message body. Do not echo Slack workspace ids or webhook URLs — those are sensitive. Tell
the user how to disable: "you can pause this alert by setting `enabled: false` via
`error-tracking-alerts-partial-update` or by toggling it in the destinations UI."

## Naming convention

Use `<trigger> · <channel> (auto)` so the user can scan their alert list and spot agent-created entries.
Examples:

- `Issue spiking · #oncall (auto)`
- `Issue reopened · #regressions-webhook (auto)`
- `Issue created · Linear/Eng (auto)`

Do not use the issue title in the name — alerts can match many issues, and the title becomes stale once
the issue evolves.

## Token-economy rules

- One full `posthog:error-tracking-alerts-list` scan up front (`type: ["internal_destination"]`,
  `limit: 1000`, paging through `next` if present), not per candidate — and not a single default-page
  call, which caps at 100 rows and misses destinations on large projects.
- Reuse a single integration lookup for multiple alerts going to the same workspace.
- Confirm the channel / URL with the user **before** creating each alert. Never batch-create alerts to a
  destination the user has not explicitly named.
- Cap iteration at 1 round per alert. If the user wants three alerts, that's three create calls — not
  three create calls per alert.

## Output

Report what you did, in this shape:

- For each shipped alert: name, trigger event, destination (channel name or webhook host — never the
  full URL), enabled state.
- For each skipped alert: trigger + channel + why (already exists, user declined, missing integration).
- Anything the user should do next: enable the spike detection config (if they picked `_spiking` and the
  detector hasn't been turned on), wire up source maps (so the alert's stack trace links resolve), or
  tune the alert filters after watching it for a day.
