---
name: creating-broadcasts
description: 'Create and send a PostHog broadcast — a one-time or scheduled email send to an audience of people, built as a workflow with kind: broadcast. Covers composing the batch trigger + email + exit graph, authoring the email, sizing the audience with a blast-radius preview, the confirm_token discipline, sending now or on a schedule, and monitoring delivery. Use when asked to send a broadcast, blast, newsletter, announcement, or one-time send, to "email everyone who…", or to set up a recurring/scheduled send to an audience.'
---

# Creating broadcasts

A **broadcast** is a one-time or scheduled email send to an audience — the customer.io-style "email everyone who matches these filters". Under the hood it is a workflow (`HogFlow`) with `kind: "broadcast"`: a `batch` trigger (the audience), exactly one `function_email` action (the email), and an `exit` action. Because it is a plain workflow, every tool from the **[building-workflows]** skill applies; this skill is the end-to-end recipe.

The cardinal rule: **a broadcast sends real email to real people, so never dispatch or schedule without showing the user the exact audience size and getting their explicit confirmation.** The tooling enforces this mechanically (see step 4), but the conversation must do it too.

## The recipe

1. [Create the draft](#1-create-the-draft) — `workflows-create` with `kind: "broadcast"`.
2. [Author the email](#2-author-the-email) — inline content or a library template.
3. [Optional: conversion goal](#3-optional-conversion-goal).
4. [Size the audience and confirm](#4-size-the-audience-and-confirm) — `workflows-blast-radius`.
5. [Enable, then send or schedule](#5-enable-then-send-or-schedule) — `workflows-enable` + `workflows-run-batch` / `workflows-schedule-create`.
6. [Monitor](#6-monitor) — `workflows-list-batch-jobs`, `workflows-stats`.

## 1. Create the draft

Call `workflows-create` with `kind: "broadcast"`, `status: "draft"`, and the three-node graph. Read [building-workflows]'s `references/graph-schema.md` before improvising any node shape — a malformed node saves but breaks the visual editor.

```json
{
  "name": "October product update",
  "description": "One-time announcement to all pro-plan users.",
  "kind": "broadcast",
  "status": "draft",
  "exit_condition": "exit_only_at_end",
  "actions": [
    {
      "id": "trigger_audience",
      "name": "Audience",
      "type": "trigger",
      "config": {
        "type": "batch",
        "filters": {
          "properties": [
            { "key": "plan", "value": ["pro"], "operator": "exact", "type": "person" },
            { "key": "id", "type": "cohort", "value": 123, "operator": "in" }
          ]
        }
      }
    },
    {
      "id": "email_broadcast",
      "name": "Broadcast email",
      "type": "function_email",
      "config": {
        "template_id": "template-email",
        "message_category_type": "marketing",
        "inputs": {
          "email": {
            "value": {
              "to": { "email": "{{ person.properties.email }}", "name": "" },
              "from": { "email": "hi@example.com", "name": "Example" },
              "subject": "What's new in October",
              "text": "Plain-text fallback of the announcement…",
              "html": "<p>…</p>"
            }
          }
        }
      }
    },
    {
      "id": "exit_done",
      "name": "Exit",
      "type": "exit",
      "config": { "reason": "Broadcast sent" }
    }
  ],
  "edges": [
    { "from": "trigger_audience", "to": "email_broadcast", "type": "continue" },
    { "from": "email_broadcast", "to": "exit_done", "type": "continue" }
  ]
}
```

Audience rules (the batch trigger targets **who a person is, not what they did**):

- `config.filters.properties` takes person-property conditions (`{key, value, operator, type: "person"}`) and cohort references (`{key: "id", type: "cohort", value: <cohort_id>, operator: "in"}`). An empty `properties` array means **everyone** — legitimate, but make sure the user knows.
- **Behavioral cohorts and event/action filters are rejected** by the API ("did event X in the last M days" can't be a batch audience). Don't approximate — tell the user and offer person properties, a static cohort, or a property-based cohort instead.
- Prefer person-property conditions or a dynamic (property-based) cohort, which re-evaluate as people qualify; a static cohort is a frozen list for an explicit given set.
- Never send `bytecode` anywhere; the server compiles it from `properties`.

## 2. Author the email

Compose email content with the **[designing-email-templates]** skill — it covers the design JSON, Liquid personalization (`{{ person.properties.first_name | default: 'there' }}`), and the mandatory unsubscribe link for marketing email (`{{ unsubscribe_url }}`).

Two ways to get content into the step:

- **Reference a library template**: list with `workflows-list-email-templates`, or create one with `workflows-create-email-template`, then put its UUID in the step's `config.template_uuid` (never in `template_id`, which stays the literal `template-email`). The template's subject/text/html/design are snapshotted into the step at save; you still supply `from` and `to`. Later template edits do **not** propagate to the step.
- **Edit the step directly** with `workflows-patch-action-email`: id-addressed design operations plus an `email_patch` merge for subject/preheader/text/recipients, with the HTML re-rendered server-side. Prefer it over `workflows-patch-graph` `update_action` for email content — patching `design` via `update_action` leaves the stored `html` stale.

Always include a real plain-text `text` body — clients that block rich content show only `text`.

## 3. Optional: conversion goal

To measure whether recipients did something after the send, set the workflow's top-level `conversion` field (via `workflows-create` or `workflows-update`):

```json
"conversion": {
  "events": [{ "filters": { "events": [{ "id": "upgrade completed", "name": "upgrade completed", "type": "events" }] } }],
  "filters": [],
  "window_minutes": 10080
}
```

- Event goals go in `events`; `filters` is only for property conditions (an event object stuffed into `filters` is invisible to the matcher).
- `window_minutes` counts from workflow entry (10080 = 7 days); `null` = no window.
- Keep `exit_condition: "exit_only_at_end"` — a broadcast sends and exits immediately, so the conversion goal is for reporting (`workflows-stats`), not flow control.

## 4. Size the audience and confirm

**Always run `workflows-blast-radius` and show the user the number before any send or schedule.** It returns:

- `affected` — how many people match the trigger's audience filters right now (recipients).
- `total` and `limit` — total persons and the per-team cap (a send whose audience exceeds `limit` is rejected).
- `confirm_token` — proof this exact audience was previewed.

The dispatch tools are structurally unskippable:

- `workflows-run-batch` and `workflows-schedule-create` both require `acknowledged_affected_count` (the number you showed the user and they explicitly confirmed) **and** the `confirm_token` from the same preview.
- The audience is re-sized at dispatch: if the count drifted from what you acknowledged, the call is rejected — re-preview, re-confirm with the user, retry.
- The `confirm_token` **expires after 15 minutes** and goes stale when the audience filters change. Either way, re-run `workflows-blast-radius` and get a fresh confirmation.

Never size and fire in one step. Show the count ("This will email **1,234 people**"), wait for the user's explicit yes, then dispatch.

## 5. Enable, then send or schedule

A batch workflow does **not** fire on enable — enabling only arms it. Both dispatch paths require `status == "active"` first:

1. `workflows-enable` — flips the draft to `active`. Get the user's go-ahead as part of the send confirmation; enabling a broadcast by itself sends nothing.
2. Then either:

**Send now** — `workflows-run-batch` with `workflow_id`, `acknowledged_affected_count`, and `confirm_token`. One run per matching person, immediately.

**Schedule** — `workflows-schedule-create` with `workflow_id`, `rrule`, `starts_at` (ISO 8601), `timezone` (IANA, default UTC), plus the same acknowledgement pair. Each firing re-broadcasts to whoever matches the audience filters **at fire time**.

- **One-time scheduled send**: `rrule: "FREQ=DAILY;COUNT=1"` with `starts_at` at the desired future moment — it fires once and never again.
- Recurring examples: every Monday 9am — `rrule: "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"`, `timezone: "America/New_York"`; first of the month — `rrule: "FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=8;BYMINUTE=0"`. Occurrences must be at most once per hour.
- Confirm with `workflows-get` that `status == "active"` **and** the read-only `schedules` field has an active entry.

Content edits after enabling stage a draft that must go through `workflows-publish` (preview impact, echo it to the user, confirm) — see [building-workflows] § Changing a live workflow.

## 6. Monitor

- `workflows-list-batch-jobs` — past runs for the broadcast (one-off and schedule-triggered), each with the audience filters and variables it used. Run outcome isn't on the job row — use stats/logs.
- `workflows-stats` — time-series success/failure plus email engagement: read `email_opened` and `email_link_clicked` against (`email_sent` − `email_untracked`), and `email_delivered` for deliverability. Conversion counts appear here when a goal is set.
- `workflows-logs` / `workflows-list-invocations` — per-recipient traces when sends fail.
- Point the user at **`/workflows/broadcasts`** in the app — the broadcasts list and per-broadcast detail (`/workflows/broadcasts/<id>`) are the human-facing view of everything above.

[building-workflows]: ../building-workflows/SKILL.md
[designing-email-templates]: ../designing-email-templates/SKILL.md
