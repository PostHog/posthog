---
name: investigating-error-issue
description: >
  Investigates a single PostHog error tracking issue end-to-end. Use when
  the user provides an issue ID or fingerprint, or pastes an issue URL
  (`/error_tracking/<fingerprint>`) and wants to understand the error — who it
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

| Tool                                             | Purpose                                                                                     |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `posthog:error-tracking-issues-resolve-retrieve` | Resolve a fingerprint or legacy issue ID to the issue's current internal ID                 |
| `posthog:query-error-tracking-issue`             | Compact issue details (status, assignee, top frame, release, aggregates)                    |
| `posthog:query-error-tracking-issue-events`      | Sampled `$exception` events with stack, URL, browser, `$session_id`                         |
| `posthog:execute-sql`                            | Breakdowns, release / flag correlations, surrounding events + console logs around the error |
| `posthog:query-logs`                             | OTEL log entries around the error timestamp for server-side issues                          |
| `posthog:query-session-recordings-list`          | Linked replays (delegate ranking to `finding-replay-for-issue`)                             |
| `posthog:read-data-schema`                       | Confirm property keys before filtering on them                                              |

## Workflow

### Step 0 — Resolve a pasted URL or fingerprint

Error tracking issue URLs use the exact fingerprint as one percent-encoded path segment. If the user pastes a URL,
percent-decode the segment after `/error_tracking/` exactly once, then resolve it before calling tools that require an
internal issue ID:

```json
posthog:error-tracking-issues-resolve-retrieve
{
  "identifier": "<decoded_fingerprint_or_legacy_issue_id>"
}
```

Use the returned `id` for the remaining steps. The resolver matches an exact fingerprint first and only treats a UUID
as a legacy issue ID when no fingerprint matches. This also follows fingerprints to their current issue after a merge
or split.

### Step 1 — Establish the issue baseline

Fetch the issue record with its compact aggregates and a sparkline:

```json
posthog:query-error-tracking-issue
{
  "issueId": "<issue_id>",
  "dateRange": { "date_from": "-30d" },
  "includeSparkline": true,
  "volumeResolution": 12
}
```

Capture: `name`, `description`, `status`, `first_seen`, `last_seen`, `assignee`,
total `occurrences` / `users` / `sessions`, top in-app frame, latest release
metadata, and the volume buckets.

The sparkline tells you the shape — flat, spike, ramp, or recurring — and that
shape drives the rest of the investigation. If the user only asked a status
question, skip `includeSparkline` to save tokens.

### Step 2 — Pull a sample exception event

A captured event has the stack frames, URL, browser, and properties needed to
reason about cause. Pull a recent sample first, then an early one to compare.

```json
posthog:query-error-tracking-issue-events
{
  "issueId": "<issue_id>",
  "limit": 1,
  "verbosity": "stack"
}
```

Use `verbosity: "raw"` only if the truncated stack hides the answer. The tool
defaults to `onlyAppFrames: true`, which strips vendor frames; flip to `false`
when the bug appears to live in a third-party library — or when the response
comes back with `stacktrace.type: "resolved"` but no frames at all (common for
minified bundles where every frame looks vendor-y to the resolver, e.g. React
production builds).

For the earliest sample, narrow `dateRange` to a tight window around the
issue's `first_seen` (e.g. set `date_from` slightly before and `date_to`
slightly after) and pass `orderDirection: "ASC"` so you get the earliest
event in the window rather than the latest — the tool defaults to `DESC`,
which would return a recent event and silently duplicate the first call.
If recent and earliest events look materially different — different stack
root, different URL pattern — the issue may be a grouping mistake. Flag for
`grouping-noisy-errors` instead of continuing as if it were one bug.

### Step 3 — Run breakdowns to isolate the cause

Breakdowns aren't a typed tool — drop into `execute-sql`. Run only the
breakdowns the issue's shape suggests; each one costs a query and clutters the
synthesis.

| Sparkline shape   | First breakdown to try                                                   |
| ----------------- | ------------------------------------------------------------------------ |
| Spike from zero   | By app version / release — almost always a deploy regression (see below) |
| Steady-state high | By browser / OS — rendering or platform-specific bug                     |
| Ramp              | By geography or feature flag — gradual rollout exposure                  |
| Bursts then quiet | By time of day or `$current_url` — scheduled job or specific page        |

#### Picking the right version property

PostHog emits three version-shaped fields. They mean different things and only
one of them answers "what version of the user's app introduced this?":

| Property              | What it is                                                | Auto-captured by                                                                   | Use for                                                                  |
| --------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `$exception_releases` | Cymbal-managed release map, keyed by release ID           | Only when SDK publishes release metadata (e.g. sourcemap upload tied to a release) | Most precise release attribution **when present**                        |
| `$app_version`        | The user's deployed app version                           | iOS (`CFBundleShortVersionString`), React Native (Expo / react-native-device-info) | "What deploy of my app introduced this?" — the question users care about |
| `$lib_version`        | The PostHog SDK library version (e.g. posthog-js 1.298.0) | Every SDK on every event                                                           | The narrow "did upgrading the PostHog SDK introduce this?" question      |

`$lib_version` is on virtually every event, which makes it tempting — but it's
the PostHog library version, not the user's app version. A constant
`$lib_version` paired with a spike means the user shipped a regression in
their own code with the SDK unchanged, which is the common case. Reach for
`$lib_version` only when nothing else is populated and you're explicitly
asking "did upgrading PostHog cause this?".

Web / server / Node / Java / Python projects do **not** auto-capture
`$app_version` — the customer has to set it (via `register`, a context
provider, or `before_send`). If the breakdown comes back with one
`$app_version` row of all-NULL, say so explicitly in the synthesis and
suggest the customer wire it up; falling back to `$exception_releases` or to
a per-day timeline by `first_seen` keeps the investigation moving.

Example (`$app_version` — populated automatically on mobile, manually on
web / server):

```sql
posthog:execute-sql
SELECT
    properties.$app_version AS app_version,
    count() AS occurrences,
    uniq(person_id) AS users,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE event = '$exception'
    AND (issue_id = '<issue_id>' OR properties.$exception_issue_id = '<issue_id>')
    AND timestamp > now() - INTERVAL 30 DAY
GROUP BY app_version
ORDER BY occurrences DESC
LIMIT 20
```

The `(issue_id = ... OR properties.$exception_issue_id = ...)` pattern
mirrors the canonical `build_issue_where` clause from
`products/error_tracking/backend/api/query_utils.py`. `issue_id` is the
resolved virtual field on `events` (it follows fingerprint overrides so
merged/split issues route correctly); `properties.$exception_issue_id` is
the raw event property captured at ingestion. Filtering on only the property
silently undercounts events for issues that have been merged or split.

If `first_seen` for one `app_version` is much later than the issue's overall
`first_seen`, that release introduced or worsened the bug — strong root-cause
signal. If every row is `NULL`, the SDK isn't reporting an app version on
this project (common on web / server) — switch to `$exception_releases` if
the customer ships releases, or fall back to a `toDate(timestamp)` timeline.

When `$exception_releases` is populated, it's a JSON dict keyed by release
ID. There is no top-level `$release` property; query `$exception_releases`
directly when you need release attribution and the customer has it wired up.

Repeat with `properties.$browser`, `properties.$os`, `properties.$current_url`,
or any feature flag the project tags errors with.

### Step 4 — Check feature flag exposure

If the user suspects an experiment or rollout, check whether affected users had
a flag enabled when the error fired.

To enumerate which flags were evaluated on affected users, parse the
`$active_feature_flags` property — it is materialized as a `Nullable(String)`
JSON-encoded column in ClickHouse, so `arrayJoin(properties.$active_feature_flags)`
directly will fail. `JSONExtract` is the working pattern, but you must coerce the
argument to a non-nullable String first: ClickHouse refuses to return a nested
`Array(String)` from `JSONExtract` when the input is `Nullable`, and this type
error is raised at query planning, so the `notEmpty(...)` guard in the WHERE
clause does not prevent it. Wrap the argument in `ifNull(..., '[]')` (or
`assumeNotNull(...)`):

```sql
posthog:execute-sql
SELECT
    arrayJoin(JSONExtract(ifNull(toString(properties.$active_feature_flags), '[]'), 'Array(String)')) AS flag,
    count() AS occurrences,
    uniq(person_id) AS users
FROM events
WHERE event = '$exception'
    AND (issue_id = '<issue_id>' OR properties.$exception_issue_id = '<issue_id>')
    AND timestamp > now() - INTERVAL 14 DAY
    AND notEmpty(toString(properties.$active_feature_flags))
GROUP BY flag
ORDER BY occurrences DESC
LIMIT 20
```

Caveat: every event captures every evaluated flag key, so this enumeration often
returns identical counts across flags and **doesn't tell you which flag
correlates with the error** — only which were on the user. To actually test a
hypothesis, query the per-flag value column `properties.$feature/<flag-key>`,
which carries the evaluated value (`true`/`false`/variant name):

```sql
posthog:execute-sql
SELECT
    properties.`$feature/my-flag-key` AS variant,
    count() AS occurrences,
    uniq(person_id) AS users
FROM events
WHERE event = '$exception'
    AND (issue_id = '<issue_id>' OR properties.$exception_issue_id = '<issue_id>')
    AND timestamp > now() - INTERVAL 14 DAY
GROUP BY variant
ORDER BY occurrences DESC
```

Compare the variant split here to the project's overall exposure on the same
flag in the same window. Disproportionate representation of one variant
suggests the flag is involved in the cause — not a guarantee, but a strong
hypothesis.

### Step 5 — Reconstruct what happened around the error

Use the `$session_id` from the sample event in step 2 to pull the activity
surrounding the exception. Three sources stack on each other; run the ones
that make sense for the SDK that captured the error.

#### 5a. Surrounding events (client SDKs by `$session_id`)

Mirrors the ET frontend session timeline. Pulls custom events, page views,
and other exceptions captured under the same session within a ±1h window:

```sql
posthog:execute-sql
SELECT
    uuid,
    event,
    timestamp,
    properties.$lib AS lib,
    properties.$current_url AS url
FROM events
WHERE $session_id = '<session_id_from_step_2>'
    AND (event = '$exception' OR event = '$pageview' OR left(event, 1) != '$')
    AND timestamp >= toDateTime('<error_timestamp>', 'UTC') - INTERVAL 1 HOUR
    AND timestamp <= toDateTime('<error_timestamp>', 'UTC') + INTERVAL 1 HOUR
ORDER BY timestamp ASC
LIMIT 100
```

The `left(event, 1) != '$'` clause drops PostHog autocapture / system events
while keeping every custom event. The `OR event = '$pageview'`/`'$exception'`
exceptions re-add the two system events worth seeing on the timeline. This is
the same filter the ET UI uses.

Mixed `$lib` values in the output are a feature, not noise. When a server SDK
propagates `$session_id` from the client request (PostHog's own backend does
this), the timeline shows server-side activity inline with the browser side —
"both SDKs when available" for free. Skim the lib column to see how each row
was produced.

The skill defaults to a ±1h window because that's what the UI uses; widen it
when an issue's actions are slow (long batch jobs, background workers) or
tighten it when only the seconds right before the throw matter.

#### 5b. Console logs (web / React Native session replay)

When session replay is enabled, the replay pipeline emits `console.*` calls
into the `log_entries` table tagged with the same session id. Pull them with
the matching window:

```sql
posthog:execute-sql
SELECT timestamp, level, message
FROM log_entries
WHERE log_source = 'session_replay'
    AND log_source_id = '<session_id_from_step_2>'
    AND timestamp >= toDateTime('<error_timestamp>', 'UTC') - INTERVAL 1 HOUR
    AND timestamp <= toDateTime('<error_timestamp>', 'UTC') + INTERVAL 1 HOUR
ORDER BY timestamp ASC
LIMIT 200
```

`log_source = 'session_replay'` is the discriminator — `log_entries` is shared
with other sources. Empty results are common: either replay isn't enabled, or
this specific session wasn't recorded. Mention that in the synthesis rather
than treating it as a failure.

#### 5c. Server logs around the error (OTEL via `query-logs`)

For server-side exceptions, correlate the exception timestamp with OTEL log
entries the customer ingests. Many projects don't ingest logs at all — if
`query-logs` returns nothing or errors, say so and move on. Discover available
services first with `logs-attribute-values-list` when you don't know which
service produced the error.

```json
posthog:query-logs
{
  "query": {
    "dateRange": {
      "date_from": "<error_timestamp minus 5 minutes>",
      "date_to":   "<error_timestamp plus 5 minutes>"
    },
    "severityLevels": ["error", "warn"],
    "serviceNames": ["<service.name if known>"],
    "limit": 50,
    "orderBy": "earliest"
  }
}
```

Caveats worth knowing before relying on this output:

- Logs are ingested separately from events and typically have shorter retention.
  Old exceptions may return empty even though the issue is still active.
- `trace_id` / `span_id` come back zero-padded (`"00000000..."`) when not set.
  Trace-based correlation only works for explicitly instrumented requests, not
  for every event.
- `service.name` is a resource attribute. Narrow with `serviceNames` rather
  than a free-text `searchTerm` when you know the producer.

#### 5d. Find a representative replay

Hand off to `finding-replay-for-issue` when picking the _best_ session matters —
popular issues link hundreds of recordings, mostly short crash fragments or
idle-tab sessions, and that skill applies the duration / active-time / recency
ranking that finds the one most likely to show the cause. Hand off too when the
user asks for "a replay" without specifying which.

Skip the hand-off and pull a recording inline via `query-session-recordings-list`
with `session_ids` from the sample exception events you already fetched in step 2
when only a handful of sessions are linked, the user already named a specific
session, or any working example will do (e.g. proving the error reproduces).

If neither path returns a recording, mention that session replay may not be
enabled for the affected users — useful context, not a failure.

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

- The canonical join key from events to an issue is the resolved `issue_id`
  virtual field, with `properties.$exception_issue_id` as fallback — see Step 3
  for the reason and the `build_issue_where` pattern.
- For a "what version introduced this?" breakdown, prefer `$app_version` (the
  user's deployed app version, auto-captured on iOS / React Native and
  manually set on web / server) or `$exception_releases` when populated. Avoid
  `$lib_version` for this question — it's the PostHog SDK library version, not
  the user's app. See the "Picking the right version property" subsection in
  Step 3.
- If the issue spans more than 30 days, widen the date range explicitly.
  Defaults often truncate the original `first_seen` event off the breakdown.
- Don't propose a fix in the synthesis unless the cause is obvious from the
  sample stack. Hypotheses backed by data are more useful than confident
  guesses.
- If `query-error-tracking-issue` returns an `external_issues` array, the issue
  is already linked to a Linear / Jira / GitHub ticket. Mention the link in the
  synthesis so the user doesn't open a duplicate.
