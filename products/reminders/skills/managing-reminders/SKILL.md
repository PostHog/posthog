---
name: managing-reminders
description: 'Create and manage PostHog reminders — private, human-paced nudges that fire as in-app notifications on a schedule, optionally linked to a PostHog resource. Use when the user says "remind me to…", wants a one-off or recurring nudge (daily/weekly/monthly/yearly, a cron schedule, or a specific date/time), wants to be reminded to look at a dashboard, insight, experiment, feature flag, survey, notebook, replay, or error, or wants to list, change, or cancel their reminders. Covers when to pick a reminder over an alert or subscription, the one-off vs recurring vs cron schedule field mappings, timezones, and attaching a resource.'
---

# Managing reminders

This skill guides you through creating and managing PostHog reminders.
A reminder is a private, human-paced nudge to yourself: it fires an in-app notification
on a schedule, with no condition attached. It can optionally link to a PostHog resource.

## When to use this skill

Use this skill when the user:

- Says "remind me to…", "nudge me", "ping me", or "don't let me forget"
- Wants a one-off reminder at a specific date/time
- Wants a recurring reminder (every day, weekly, every Monday, weekdays, monthly, etc.)
- Wants to be reminded to review a specific dashboard, insight, experiment, flag, survey, notebook, replay, or error
- Wants to see, change, or cancel reminders they have set

## Reminder vs alert vs subscription

These three look similar but solve different jobs. Pick the right one:

- **Reminder** — a human-paced nudge to yourself with **no condition**. It just fires an
  in-app notification on a schedule ("remind me to review the launch dashboard every Monday").
  If the user says **"remind me to…"**, it is a reminder.
- **Alert** — watches an insight's metric on a schedule and notifies only when a
  **threshold or anomaly condition is met** ("tell me if signups drop below 100").
- **Subscription** — delivers an insight or dashboard **export/snapshot** on a schedule via
  email, Slack, or webhook ("email me this dashboard every morning").

If there is a condition to evaluate, it is an alert. If there is an export to deliver, it is a
subscription. If it is just a timed nudge to a person, it is a reminder.

## Scheduling shapes

A reminder uses **exactly one** of `scheduled_at`, `recurrence_interval`, or `cron_expression`.
Providing zero or more than one is rejected.

### One-off

Set `scheduled_at` to a future ISO 8601 timestamp. The reminder fires once, then becomes `completed`.

| User says                   | Field                                                |
| --------------------------- | ---------------------------------------------------- |
| "remind me tomorrow at 3pm" | `scheduled_at: <tomorrow 15:00 in the user's tz>`    |
| "remind me on Jan 5 at 9am" | `scheduled_at: "2026-01-05T09:00:00"` (+ `timezone`) |

### Preset recurring

Set `recurrence_interval` to one of `daily`, `weekly`, `monthly`, `yearly`.

| User says     | Field                            |
| ------------- | -------------------------------- |
| "every day"   | `recurrence_interval: "daily"`   |
| "every week"  | `recurrence_interval: "weekly"`  |
| "every month" | `recurrence_interval: "monthly"` |
| "every year"  | `recurrence_interval: "yearly"`  |

### Cron recurring

Set `cron_expression` to a 5-field cron string (`min hour day-of-month month day-of-week`) when
the cadence is a specific weekday or time the presets can't express.

| User says                  | Field                             |
| -------------------------- | --------------------------------- |
| "every Monday at 9am"      | `cron_expression: "0 9 * * 1"`    |
| "weekdays at 8:30"         | `cron_expression: "30 8 * * 1-5"` |
| "1st of the month at noon" | `cron_expression: "0 12 1 * *"`   |

A reminder may fire **at most 4 times per day** — a more frequent cron (e.g. hourly) is rejected.

## Timezone

Always pass `timezone` as the user's IANA zone (e.g. `"America/New_York"`) when you know it, so
wall-clock times like "9am" resolve to the right moment. If omitted, it defaults to the **project
timezone**. Cron and preset schedules resolve in this zone; `scheduled_at` is an absolute instant,
so include its offset or rely on the same zone.

## Attaching a resource

To link the reminder to a PostHog object, set `resource_type` and `resource_id` **together**.
The fired notification deep-links to that object. The resource must already exist in the project.

| `resource_type`  | `resource_id` is the… |
| ---------------- | --------------------- |
| `dashboard`      | numeric id            |
| `insight`        | short_id              |
| `experiment`     | numeric id            |
| `feature_flag`   | numeric id            |
| `survey`         | id                    |
| `notebook`       | short_id              |
| `replay`         | session_id            |
| `error_tracking` | issue id              |

Resolve the id first if the user gives you a name or URL (e.g. fetch the insight to get its
`short_id`). Omit both fields for a standalone reminder with no linked resource.

## Privacy and lifecycle

- Reminders are **private to the creating user** and scoped to the **current project**. Other
  users never see them.
- They fire as **in-app notifications** — not email, Slack, or webhook.
- A **one-off** becomes `completed` after it fires.
- A **recurring** reminder stays `active` until deleted, or until its optional `end_date` passes
  (then it becomes `completed`).
- A one-off whose delivery permanently fails becomes `errored` — surface this via `reminders-list`
  when reporting on a user's reminders.

## The MCP tools

- `reminder-create` — create a reminder
- `reminders-list` — list the user's reminders (schedule, status, next fire time)
- `reminder-get` — get one reminder by id
- `reminder-update` — update title, message, schedule, timezone, end date, or attached resource
  (changing the schedule recomputes the next fire time)
- `reminder-delete` — delete a reminder, which stops it firing

## Worked example

User: "Remind me to review the launch dashboard every Monday at 9am."

1. Resolve the dashboard id (e.g. dashboard `67`).
2. Pick the schedule shape: a specific weekday + time → cron.
3. Pass the user's timezone if known.
4. Call `reminder-create`:

```json
{
  "title": "Review the launch dashboard",
  "resource_type": "dashboard",
  "resource_id": "67",
  "cron_expression": "0 9 * * 1",
  "timezone": "America/New_York"
}
```

Confirm back to the user when it will next fire (use `next_fire_at` from the response), and that
it will keep firing weekly until they delete it.
