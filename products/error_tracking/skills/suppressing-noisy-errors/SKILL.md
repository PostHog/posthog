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

| Tool                                              | Purpose                                                                   |
| ------------------------------------------------- | ------------------------------------------------------------------------- |
| `posthog:query-error-tracking-issues-list`        | Find suppression candidates by volume and impact                          |
| `posthog:query-error-tracking-issue-events`       | Inspect sampled `$exception` events to confirm the pattern                |
| `posthog:execute-sql`                             | Pre-create volume estimate (count + distinct users) for the chosen filter |
| `posthog:error-tracking-suppression-rules-list`   | Check existing suppression rules                                          |
| `posthog:error-tracking-suppression-rules-create` | Create the suppression rule                                               |

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

| Noise pattern                       | Recommended filter                                                                                                                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Browser extension errors            | `$exception_sources icontains "chrome-extension://"`                                                                                                                                                         |
| ResizeObserver loop                 | `$exception_values icontains "ResizeObserver loop"` (the message is specific; a type filter is optional)                                                                                                     |
| Cross-origin "Script error."        | `$exception_values icontains "Script error."` AND `$exception_types regex '"Error"'`                                                                                                                         |
| Bot user agents                     | `$raw_user_agent regex "(HeadlessChrome\|bot\|crawler\|spider)"` (case-insensitive — `$user_agent` works too, but the raw header is more reliable for crawler markers since parsers can normalize them away) |
| Third-party network beacon failures | `$exception_sources icontains "<vendor-domain>"` AND a type filter via `icontains` or `regex`                                                                                                                |

The canonical exception properties (`$exception_types`, `$exception_values`,
`$exception_sources`, `$exception_functions`) are arrays at capture time but
are materialized as JSON-encoded strings in ClickHouse — the stored column
literal for a TypeError is `["TypeError"]`, not `TypeError`. That changes
which operators work:

- `icontains` and `regex` work — they substring/match against the JSON literal
  (`icontains "TypeError"` becomes `ILIKE '%TypeError%'`).
- `exact` and `is_not` do **not** work for matching individual elements:
  `exact "TypeError"` compiles to `column = 'TypeError'` and never matches
  `["TypeError"]`. Use `regex '"TypeError"'` (with quotes inside the pattern)
  when you need exact-element precision — it scopes to the JSON-quoted token.
- The singular forms (`$exception_type`, `$exception_message`) and
  `$exception_stack_trace_raw` are emitted on a fraction of a percent of events;
  filtering on them produces a rule that silently never matches.

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

### Step 5 — Confirm with the user before creating

Suppression is destructive in spirit even though the API marks it
`destructive: false`. Show the user before creating:

1. The exact filter you plan to send
2. The current 7d volume that filter would have suppressed
3. The number of distinct users in that volume (highlight if it's higher than
   expected)
4. Whether it overlaps any existing suppression rules
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
        "operator": "icontains",
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
  "sampling_rate": 1
}
```

### Step 6 — Watch the rule for 24-48h

After creating the rule:

- Confirm matching events are no longer being captured (re-run the count from
  step 5; should drop to near zero)
- Watch related active issues — if their volume drops in the same window, the
  rule was scoped correctly
- If a related real issue's volume drops too (false-positive), disable the rule
  immediately and tighten the filter

If you see signs of false positives (a real issue going quiet at the same time
the rule was created), prefer disabling the rule over deleting it — that
preserves the rule's configuration for forensic review.

## Tips

- Project settings → Error tracking → Suppression rules shows the same data;
  mention this when the user asks where rules live in the UI.
- Suppression applies at ingestion. Existing issues from past events keep their
  data; only new events are dropped. To clean up past data, change the issue's
  status to `archived` or `suppressed` via
  `error-tracking-issues-partial-update`.
- For a status-only change (don't drop the data, just hide it from the active
  list), prefer `error-tracking-issues-partial-update` with `status: "suppressed"`
  over a suppression rule.
- The schema explicitly warns the model not to create match-all rules. If the
  user asks "suppress everything from extensions", still scope by stack trace or
  URL — never leave `filters` empty.
- A suppression rule that turns out to be too narrow is harmless (some noise
  leaks through). A rule that's too broad silently destroys real data — bias
  toward narrow.
