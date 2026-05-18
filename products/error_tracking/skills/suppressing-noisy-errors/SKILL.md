---
name: suppressing-noisy-errors
description: >
  Create PostHog error tracking suppression rules to drop high-volume,
  low-value errors at ingestion. Use when the user asks "stop capturing
  this error", "drop browser extension errors", "ignore ResizeObserver
  loops", "suppress bot-driven errors", or wants to reduce ingestion
  cost from noisy unactionable errors. Identifies suppression
  candidates, scopes the filter tightly, decides between full
  suppression and sampling, and confirms the rule before creating it.
  Suppressed errors are dropped permanently — this skill defaults to
  caution.
---

# Suppressing noisy errors

Suppression is destructive in spirit: matching events are dropped at ingestion and
never become issues. The wrong rule silently throws away real bugs. This skill
exists to make sure suppression is applied only to patterns that are genuinely
unactionable, with filters narrow enough to avoid swallowing unrelated errors.

## When suppression is the right tool

Suppression is the right tool when an error is:

- **Unactionable from your code** — browser extensions, third-party scripts, ad
  blockers, network beacons firing after navigation. You can't fix it because you
  didn't write it.
- **Browser engine quirks** — `ResizeObserver loop limit exceeded`,
  `Script error.`, `Non-Error promise rejection captured` with empty payloads.
- **Bot or crawler traffic** — errors firing only from headless browsers or known
  crawler user agents.
- **Sampling already enough** — for high-volume but real errors, dampen with
  `sampling_rate` instead of full suppression so you keep visibility without
  paying full cost.

Suppression is **not** the right tool when:

- The error is unactionable _today_ but might become actionable after a fix —
  use issue status `archived` or `resolved` instead so it surfaces if it returns.
- You only want to mute notifications — assign the issue to a user, change its
  status, or use notification rules.
- The error is a duplicate of another — merge or create a grouping rule
  (`grouping-noisy-errors`).

## Available tools

| Tool                                              | Purpose                                                                                              |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `posthog:query-error-tracking-issues-list`        | Find suppression candidates by volume and impact; dry-run a candidate filter via `filterGroup`       |
| `posthog:query-error-tracking-issue-events`       | Inspect sampled `$exception` events to confirm the pattern                                           |
| `posthog:execute-sql`                             | Fallback dry-run for filters that need OR groups or operators outside the `filterGroup` allowed list |
| `posthog:error-tracking-suppression-rules-list`   | Check existing suppression rules                                                                     |
| `posthog:error-tracking-suppression-rules-create` | Create the suppression rule                                                                          |
| `posthog:error-tracking-issues-partial-update`    | Hide past data via issue status without dropping events at ingestion                                 |

## Workflow

### Step 1 — Identify candidates

High occurrences with low distinct users is the strongest noise signal — one
user (or one bot) producing many events.

```json
posthog:query-error-tracking-issues-list
{
  "status": "active",
  "orderBy": "occurrences",
  "orderDirection": "DESC",
  "dateRange": { "date_from": "-7d" },
  "limit": 30,
  "volumeResolution": 0
}
```

Look for:

- High `occurrences`, low `users` ratio (e.g., 50,000 occurrences, 3 users → likely
  bot or extension loop)
- Exception messages matching known noise patterns: `ResizeObserver loop`,
  `Script error.`, extension namespaces (`chrome-extension://`,
  `moz-extension://`, `safari-extension://`)
- Stack traces dominated by third-party domains the user doesn't control

### Step 2 — Confirm the pattern

For each candidate, pull a sample of `$exception` events and check that the
pattern matches what you intend to suppress:

```json
posthog:query-error-tracking-issue-events
{
  "issueId": "<candidate_issue_id>",
  "limit": 10,
  "verbosity": "stack"
}
```

`onlyAppFrames` defaults to `true`, but for noise investigation you usually
want the third-party frames visible — pass `onlyAppFrames: false` so extension
URLs and vendor domains show up in the stack.

Confirm:

- The exception type or message text is consistent across the sample
- The URLs / user agents / browsers don't include real user traffic mixed in with
  the noise
- Suppressing this pattern won't hide a future real bug that happens to share
  the type

If any sample doesn't match, narrow the filter or skip the candidate.

### Step 3 — Scope the filter tightly

Suppression rules are configured with the same filter shape as grouping rules.
The `error-tracking-suppression-rules-create` tool description warns explicitly:
do **not** create match-all rules and do **not** create overly broad rules.
Match on the most specific property combination you can:

| Noise pattern                       | Recommended filter                                                                                                                          |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Chrome extension errors             | `$exception_sources icontains "chrome-extension://"`                                                                                        |
| Firefox extension errors            | `$exception_sources icontains "moz-extension://"`                                                                                           |
| Safari extension errors             | `$exception_sources icontains "safari-extension://"`                                                                                        |
| ResizeObserver loop                 | `$exception_values icontains "ResizeObserver loop"` (the message is specific; a type filter is optional)                                    |
| Cross-origin "Script error."        | `$exception_values icontains "Script error."` AND `$exception_types exact "Error"`                                                          |
| Bot user agents                     | `$raw_user_agent regex "(?i)bot"` for a single term; see the alternation pattern below for matching several bot/crawler markers in one rule |
| Third-party network beacon failures | `$exception_sources icontains "<vendor-domain>"` AND a type filter (e.g. `$exception_types exact "TypeError"`)                              |

The canonical exception properties (`$exception_types`, `$exception_values`,
`$exception_sources`, `$exception_functions`) are arrays at capture time. The
property filter compiler [special-cases them](https://github.com/PostHog/posthog/blob/master/posthog/hogql/property.py#L904) — it parses the
JSON-materialized column and wraps the filter in
`arrayExists(v -> ..., JSONExtract(...))`, so all the standard operators
(`exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`) work
against individual elements with the bare value: `exact "TypeError"`, not
`exact '["TypeError"]'` or `regex '"TypeError"'`.

The singular forms (`$exception_type`, `$exception_message`) and
`$exception_stack_trace_raw` are emitted on a fraction of a percent of events;
filtering on them produces a rule that silently never matches.

Note that the `regex` operator on suppression and grouping rules compiles to
the HogVM `Operation::Regex`, which is **case-sensitive**. Use the `(?i)`
inline flag for case-insensitive matching (e.g. `(?i)headlesschrome`).

For matching multiple bot or crawler terms, use bare pipes for alternation.
Pass this as the `value` field of the regex filter when calling the API
(`$raw_user_agent` is more reliable than the parsed `$user_agent`, which some
parsers normalize away from crawler markers):

```text
(?i)(HeadlessChrome|bot|crawler|spider)
```

Whenever possible, AND together two or more conditions — type plus message, or
message plus URL pattern — so the rule is specific to the real noise.

### Step 4 — Decide: suppress or sample

If you want to keep some visibility, use `sampling_rate` between 0 and 1:

- `sampling_rate: 1` — drop everything matching (full suppression)
- `sampling_rate: 0.95` — drop 95% of matching events, keep 5% as sentinel data
- `sampling_rate: 0.5` — half-rate, useful for high-volume but real errors

Default to a non-1.0 sampling rate when there's any doubt that the pattern is
purely noise. You can tighten to 1.0 later once the data shows the rule isn't
catching real issues.

### Step 5 — Dry-run the filter against live data

Before asking for confirmation, run the candidate filter against the issues
list so you (and the user) can see exactly which issues the rule would have
caught over the last 7 days. `query-error-tracking-issues-list` accepts the
same property-filter shape suppression rules use via its `filterGroup`
parameter, so for a typical AND-only rule you can pass the rule's leaf
filters directly — no HogQL translation needed:

```json
posthog:query-error-tracking-issues-list
{
  "filterGroup": [
    { "type": "event", "key": "$exception_types", "operator": "exact", "value": "Error" },
    { "type": "event", "key": "$exception_values", "operator": "icontains", "value": "ResizeObserver loop" }
  ],
  "dateRange": { "date_from": "-7d" },
  "status": "all",
  "filterTestAccounts": false,
  "orderBy": "occurrences",
  "limit": 25
}
```

Important defaults to override for suppression preview:

- `status: "all"` — suppression applies regardless of issue status, so don't
  let the default `active` filter hide already-archived noise.
- `filterTestAccounts: false` — the rule will not respect the test-account
  toggle at ingestion. The preview should match production reality.

Each row is one issue the rule would catch: `name` (exception type),
`description` (sample message), `source`, `library`, plus
`aggregations.occurrences` and `aggregations.users`. The issue list **is**
the per-issue breakdown — read every row.

**The single most important safety check**: scan the result for any issue
whose `name` / `description` / `source` looks like a real bug the team
would want to fix, not noise. A filter that looks tight by message text
will routinely match unrelated issues that happen to share a phrase, and
this is the failure mode that silently destroys real data once the rule is
live. If you see anything suspicious, narrow the filter (step 3) and rerun
this step until only the genuine noise pattern is in the list.

Add up `aggregations.occurrences` and `aggregations.users` across rows for
the blast-radius totals you'll surface to the user in step 6. If you need
exact totals across more than `limit` issues, paginate with `offset` or
fall back to the HogQL aggregate at the end of this step.

For one or two concrete sample events with full stack traces, follow up on
the most suspicious-looking issue with `query-error-tracking-issue-events`:

```json
posthog:query-error-tracking-issue-events
{
  "issueId": "<id from the list>",
  "limit": 3,
  "verbosity": "stack",
  "onlyAppFrames": false
}
```

#### When you must fall back to execute-sql

`filterGroup` is **flat AND only**. Drop into HogQL when:

- The rule uses `type: "OR"` at the outer group or any nested OR.
- The rule uses operators not supported by `filterGroup` (e.g. `between`,
  `in`, `semver_*`).
- You want a precise event-level count rather than per-issue aggregates.

The HogQL shape mirrors what the suppression rule bytecode compiles to.
The materialized property column is nullable, so the `coalesce(..., '[]')`
wrapper is required — without it ClickHouse rejects the query with
"Nested type Array(String) cannot be inside Nullable type":

```sql
SELECT
  count() AS matched,
  count(DISTINCT distinct_id) AS users,
  count(DISTINCT properties.$exception_issue_id) AS issues
FROM events
WHERE event = '$exception'
  AND timestamp > now() - INTERVAL 7 DAY
  AND arrayExists(
    v -> ifNull(ilike(v, '<pattern>'), 0),
    JSONExtract(coalesce(properties.$exception_values, '[]'), 'Array(String)')
  )
```

Use `ilike` for `icontains`, plain equality for `exact`, `match(v,
'<pattern>')` for `regex`. The rule's `regex` is case-sensitive — add
`(?i)` inline if needed.

### Step 6 — Confirm with the user before creating

Suppression is destructive in spirit even though the API marks it
`destructive: false`. Show the user before creating:

1. The exact filter you plan to send
2. The list of issues from step 5 with their `occurrences` and `users`,
   plus the aggregate totals — call out any rows that look like real bugs
3. Whether it overlaps any existing suppression rules
   (`posthog:error-tracking-suppression-rules-list` first)

Wait for explicit confirmation. Then create:

```json
posthog:error-tracking-suppression-rules-create
{
  "filters": {
    "type": "AND",
    "values": [
      {
        "type": "event",
        "key": "$exception_types",
        "operator": "exact",
        "value": "Error"
      },
      {
        "type": "event",
        "key": "$exception_values",
        "operator": "icontains",
        "value": "ResizeObserver loop"
      }
    ]
  },
  "sampling_rate": 0.95
}
```

Start at `0.95` (drop 95%, keep 5% as sentinel data) so you can confirm the
rule isn't catching real errors before tightening to `1.0`.

### Step 7 — Watch the rule for 24-48h

After creating the rule:

- Confirm matching events are no longer being captured by running the same
  filter against a short window scoped to **after** the rule was created
  (e.g. `WHERE timestamp > now() - INTERVAL 1 HOUR` once an hour has passed).
  Don't re-run the 7-day estimate from step 5 — suppression only applies to
  new events, so historical events in the window will still be there and the
  count won't drop.
- Watch related active issues over the post-creation window — if their volume
  drops while non-related issues hold steady, the rule was scoped correctly
- If a related real issue's volume drops too (false-positive), ask the user to
  disable the rule via **Project settings → Error tracking → Suppression rules**
  immediately and tighten the filter before re-creating it. The MCP tools to
  edit or delete a rule (`error-tracking-suppression-rules-partial-update`,
  `-destroy`) are not enabled — the agent has no way to recover programmatically.

If you see signs of false positives (a real issue going quiet at the same time
the rule was created), prefer disabling the rule over deleting it — that
preserves the rule's configuration for forensic review.

## Tips

- Project settings → Error tracking → Suppression rules shows the same data;
  mention this when the user asks where rules live in the UI.
- Suppression applies at ingestion. Existing issues from past events keep their
  data; only new events are dropped.
- For a status-only change (don't drop the data, just hide it from the active
  list), prefer `error-tracking-issues-partial-update` with `status: "suppressed"`
  over a suppression rule.
- The schema explicitly warns the model not to create match-all rules. If the
  user asks "suppress everything from extensions", still scope by stack trace or
  URL — never leave `filters` empty.
- A suppression rule that turns out to be too narrow is harmless (some noise
  leaks through). A rule that's too broad silently destroys real data — bias
  toward narrow.
