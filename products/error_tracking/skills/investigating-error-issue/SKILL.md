---
name: investigating-error-issue
description: >
  Investigates a single PostHog error tracking issue end-to-end. Use when
  the user provides an issue ID or pastes an issue URL
  (`/error_tracking/<id>`) and wants to understand the error — who it
  affects, what triggers it, when it started, whether it correlates with
  a release, browser, OS, or feature flag, and what the next step should
  be. Pulls aggregated metrics, sample exception events, segment
  breakdowns, linked replays, and synthesizes a hypothesis-grade summary
  in one pass.
---

# Investigating an error tracking issue

When a user asks "what's going on with this error?" or pastes an issue URL, gather
the context they would otherwise have to assemble manually: who is hitting it, what
changed, where it happens, and whether a replay shows the cause.

## Available tools

| Tool                                     | Purpose                                                          |
| ---------------------------------------- | ---------------------------------------------------------------- |
| `posthog:error-tracking-issues-retrieve` | Issue metadata (description, assignee, fingerprint, status)      |
| `posthog:query-error-tracking-issues`    | Aggregated metrics (users, sessions, volume sparkline)           |
| `posthog:execute-sql`                    | Sample exception events, breakdowns, release / flag correlations |
| `posthog:query-session-recordings-list`  | Linked replays (delegate ranking to `finding-replay-for-issue`)  |
| `posthog:read-data-schema`               | Confirm property keys before filtering on them                   |

## Workflow

### Step 1 — Establish the issue baseline

Fetch the issue record and aggregated metrics in parallel.

```json
posthog:error-tracking-issues-retrieve
{ "id": "<issue_id>" }
```

```json
posthog:query-error-tracking-issues
{
  "issueId": "<issue_id>",
  "dateRange": { "date_from": "-30d" },
  "volumeResolution": 1
}
```

Capture: `name`, `description`, `status`, `first_seen`, `last_seen`, `assignee`,
`fingerprint`, total `users`, `sessions`, `occurrences`, and the volume sparkline.

The sparkline tells you the shape — flat, spike, ramp, or recurring — and that
shape drives the rest of the investigation.

### Step 2 — Pull a sample exception event

A captured event has the stack frames, URL, browser, and properties needed to
reason about cause. Pull one recent and one early sample to compare.

```sql
posthog:execute-sql
SELECT
    timestamp,
    properties.$exception_type AS type,
    properties.$exception_message AS message,
    properties.$exception_stack_trace_raw AS stack,
    properties.$current_url AS url,
    properties.$browser AS browser,
    properties.$browser_version AS browser_version,
    properties.$os AS os,
    properties.$lib AS sdk,
    properties.$lib_version AS sdk_version,
    properties.$release AS release,
    person_id
FROM events
WHERE event = '$exception'
    AND properties.$exception_issue_id = '<issue_id>'
ORDER BY timestamp DESC
LIMIT 1
```

Repeat with `ORDER BY timestamp ASC` for the earliest captured event. If they
look materially different — different stack, different URL pattern — the issue
may be a grouping mistake. Flag it for `grouping-noisy-errors` instead of
continuing the investigation as if it were one bug.

### Step 3 — Run breakdowns to isolate the cause

Run the breakdowns the issue's shape suggests. Don't run all of them blindly;
each breakdown costs a query and clutters the synthesis.

| Sparkline shape   | First breakdown to try                                            |
| ----------------- | ----------------------------------------------------------------- |
| Spike from zero   | By release / SDK version — almost always a deploy regression      |
| Steady-state high | By browser / OS — rendering or platform-specific bug              |
| Ramp              | By geography or feature flag — gradual rollout exposure           |
| Bursts then quiet | By time of day or `$current_url` — scheduled job or specific page |

Example (release):

```sql
posthog:execute-sql
SELECT
    properties.$release AS release,
    count() AS occurrences,
    uniq(person_id) AS users,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE event = '$exception'
    AND properties.$exception_issue_id = '<issue_id>'
    AND timestamp > now() - INTERVAL 30 DAY
GROUP BY release
ORDER BY occurrences DESC
LIMIT 20
```

If `first_seen` for one release is much later than the issue's overall
`first_seen`, that release introduced (or worsened) the bug — strong root-cause
signal.

Repeat with `properties.$browser`, `properties.$os`, `properties.$current_url`,
`properties.$lib_version`, or any feature flag the project tags errors with.

### Step 4 — Check feature flag exposure

If the user suspects an experiment or rollout, check whether affected users had
a flag enabled when the error fired. The `$active_feature_flags` array on the
exception event captures flags evaluated at capture time:

```sql
posthog:execute-sql
SELECT
    arrayJoin(properties.$active_feature_flags) AS flag,
    count() AS occurrences,
    uniq(person_id) AS users
FROM events
WHERE event = '$exception'
    AND properties.$exception_issue_id = '<issue_id>'
    AND timestamp > now() - INTERVAL 14 DAY
GROUP BY flag
ORDER BY occurrences DESC
LIMIT 20
```

Compare to the project's overall flag exposure in the same window.
Disproportionate representation of one flag suggests the flag is involved in
the cause — not a guarantee, but a strong hypothesis.

### Step 5 — Find a representative replay

Hand off to `finding-replay-for-issue` rather than picking blindly. That skill
ranks linked sessions by activity score, duration, and journey completeness so
the user lands on the recording most likely to show the cause.

If `finding-replay-for-issue` returns nothing, mention that session replay may
not be enabled for the affected users — useful context, not a failure.

### Step 6 — Synthesize

Present in this order:

1. **What it is** — type, message, where in the stack
2. **Who it affects** — total users, sessions, and any segment breakdown that
   stood out
3. **When it started** — `first_seen`, plus the release / version that
   introduced it if a breakdown found one
4. **Likely cause** — one or two hypotheses backed by the breakdowns above
5. **Next step** — a concrete action: investigate the suspected release, watch
   the linked replay, ping the assignee, or escalate

Keep the synthesis tight. The user wants the answer, not a tour of the data.

## Tips

- `properties.$exception_issue_id` is the canonical join key from events to an
  issue. The fingerprint also works but the issue ID is stable across
  fingerprint splits and merges.
- Some breakdowns return `null` heavily — `$release` requires the SDK to be
  configured to set it. If it's mostly null, fall back to `$lib_version`.
- If the issue spans more than 30 days, widen the date range explicitly.
  Defaults often truncate the original `first_seen` event off the breakdown.
- Don't propose a fix in the synthesis unless the cause is obvious from the
  sample stack. Hypotheses backed by data are more useful than confident
  guesses.
- If `error-tracking-issues-retrieve` returns an `external_issues` array, the
  issue is already linked to a Linear / Jira / GitHub ticket. Mention the link
  in the synthesis so the user doesn't open a duplicate.
